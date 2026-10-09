"""Completed games supervise the value head without replaying actor actions."""

import copy
from datetime import timedelta
from pathlib import Path

import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel

from keisei.training.katago_ppo import KataGoPPOAlgorithm, KataGoPPOParams, KataGoRolloutBuffer
from keisei.training.models.katago_base import KataGoBaseModel, KataGoOutput
from keisei.training.value_adapter import MultiHeadValueAdapter


class StateValueModel(KataGoBaseModel):
    def __init__(self):
        super().__init__()
        self.policy = torch.nn.Linear(3, 3)
        self.value = torch.nn.Linear(3, 3, bias=False)
        self.score = torch.nn.Linear(3, 1)
        torch.nn.init.zeros_(self.value.weight)
        self.forward_sizes = []

    def _forward_impl(self, observations):
        self.forward_sizes.append(observations.shape[0])
        return KataGoOutput(self.policy(observations), self.value(observations), self.score(observations))


def _batch(observations, categories):
    from keisei.training.outcomes import GameOutcomeBatch

    return GameOutcomeBatch(observations, torch.tensor(categories, dtype=torch.long))


def _buffer(ppo, samples=2, category=0):
    observations = torch.tensor([[1.0, 0.0, 0.0]]).repeat(samples, 1)
    masks = torch.ones(samples, 3, dtype=torch.bool)
    actions, log_probs, values = ppo.select_actions(observations, masks)
    buffer = KataGoRolloutBuffer(samples, (3,), 3)
    buffer.add(
        observations, actions, log_probs, torch.zeros_like(values),
        torch.arange(samples).float() % 2,
        torch.ones(samples, dtype=torch.bool), torch.ones(samples, dtype=torch.bool),
        masks, torch.full((samples,), category), torch.zeros(samples),
    )
    return buffer


@pytest.mark.parametrize("use_adapter", [False, True])
def test_completed_game_trains_earlier_losing_position_without_duplicate_actor_labels(use_adapter):
    model = StateValueModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=2), model)
    buffer = _buffer(ppo, category=0)
    batch = _batch(torch.tensor([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]), [2, 0])
    adapter = MultiHeadValueAdapter() if use_adapter else None
    model.forward_sizes.clear()

    metrics = ppo.update(buffer, torch.zeros(2), value_adapter=adapter, critic_batch=batch)

    assert model.value.weight.grad is not None
    assert model.value.weight.grad[:, 0].eq(0).all(), "Actor terminal label must not be counted twice"
    assert model.value.weight[2, 1] > 0, "Earlier losing position must learn a loss target"
    assert model.value.weight[0, 2] > 0, "Earlier winning position must learn a win target"
    assert model.forward_sizes == [4], "Actor and critic share one scheduled forward"
    assert metrics["value_loss"] > 0


def test_critic_observations_do_not_enter_policy_or_score_loss():
    torch.manual_seed(42)
    initial_model = StateValueModel()
    models = [copy.deepcopy(initial_model), copy.deepcopy(initial_model)]
    results = []
    for model, observations in zip(models, [torch.tensor([[0.0, 1.0, 0.0]]), torch.tensor([[0.0, 0.0, 50.0]])]):
        torch.manual_seed(91)
        ppo = KataGoPPOAlgorithm(
            KataGoPPOParams(epochs_per_batch=1, batch_size=2, lambda_value=0.0), model,
        )
        buffer = _buffer(ppo)
        metrics = ppo.update(buffer, torch.zeros(2), critic_batch=_batch(observations, [2]))
        results.append(metrics)

    for name in ["policy", "score"]:
        torch.testing.assert_close(getattr(models[0], name).weight, getattr(models[1], name).weight)
        torch.testing.assert_close(getattr(models[0], name).bias, getattr(models[1], name).bias)
    assert results[0] == results[1]


@pytest.mark.parametrize("use_adapter", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
def test_empty_or_disabled_critic_head_stays_disconnected_even_with_nan_weights(use_adapter, disabled):
    model = StateValueModel()
    with torch.no_grad():
        model.value.weight.fill_(float("nan"))
    params = KataGoPPOParams(epochs_per_batch=1, batch_size=2, lambda_value=0.0 if disabled else 1.5)
    ppo = KataGoPPOAlgorithm(params, model)
    buffer = _buffer(ppo)
    adapter = MultiHeadValueAdapter(lambda_value=params.lambda_value) if use_adapter else None
    batch = _batch(torch.tensor([[0.0, 1.0, 0.0]]), [2]) if disabled else _batch(torch.empty(0, 3), [])
    metrics = ppo.update(buffer, torch.zeros(2), value_adapter=adapter, critic_batch=batch)
    assert model.value.weight.grad is None
    assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
    assert torch.isfinite(model.policy.weight).all()


def test_active_completed_game_value_head_with_nan_weights_aborts_before_step(monkeypatch):
    model = StateValueModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=2), model)
    buffer = _buffer(ppo)
    with torch.no_grad():
        model.value.weight.fill_(float("nan"))
    steps = []
    monkeypatch.setattr(ppo.optimizer, "step", lambda *args, **kwargs: steps.append(True))
    with pytest.raises(RuntimeError, match="[Nn]on.?finite"):
        ppo.update(buffer, torch.zeros(2), critic_batch=_batch(torch.tensor([[0.0, 1.0, 0.0]]), [2]))
    assert not steps


def test_critic_partitions_reuse_all_completed_rows_with_the_actor_forward_schedule():
    model = StateValueModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=2, batch_size=2), model)
    buffer = _buffer(ppo, samples=6)
    batch = _batch(torch.tensor([[0.0, float(value), 0.0] for value in range(1, 9)]), [0, 2] * 4)
    model.forward_sizes.clear()
    ppo.update(buffer, torch.zeros(6), critic_batch=batch)
    assert model.forward_sizes == [5, 5, 4, 5, 5, 4]


@pytest.mark.parametrize("invalid", ["shape", "category", "nonfinite"])
def test_invalid_critic_batch_fails_before_forward_or_optimizer_step(invalid):
    model = StateValueModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=2), model)
    buffer = _buffer(ppo)
    observations = torch.zeros(1, 4 if invalid == "shape" else 3)
    if invalid == "nonfinite":
        observations[0, 0] = float("nan")
    batch = _batch(observations, [3 if invalid == "category" else 0])
    model.forward_sizes.clear()
    with pytest.raises((ValueError, RuntimeError), match="critic"):
        ppo.update(buffer, torch.zeros(2), critic_batch=batch)
    assert model.forward_sizes == []


def _distributed_outcome_worker(rank, init_path, result_dir, invalid_batch):
    torch.set_num_threads(1)
    dist.init_process_group(
        "gloo", init_method=f"file://{init_path}", rank=rank, world_size=2,
        timeout=timedelta(seconds=30),
    )
    try:
        torch.manual_seed(42)
        model = StateValueModel()
        wrapped = DistributedDataParallel(model, find_unused_parameters=True)
        ppo = KataGoPPOAlgorithm(
            KataGoPPOParams(epochs_per_batch=2, batch_size=2), model, forward_model=wrapped,
        )
        if invalid_batch:
            buffer = _buffer(ppo, samples=4)
            batch = _batch(torch.tensor([[0.0, 1.0, 0.0]]), [3 if rank == 1 else 0])
            model.forward_sizes.clear()
            with pytest.raises(RuntimeError, match="critic"):
                ppo.update(buffer, torch.zeros(4), critic_batch=batch)
            assert model.forward_sizes == []
        else:
            for counts in [(3, 0), (0, 2), (2, 4)]:
                count = counts[rank]
                observations = torch.tensor([[0.0, 1.0, 0.0]]).repeat(count, 1)
                categories = [2] * count
                buffer = _buffer(ppo, samples=4)
                model.forward_sizes.clear()
                metrics = ppo.update(buffer, torch.zeros(4), critic_batch=_batch(observations, categories))
                assert len(model.forward_sizes) == 4
                assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
        torch.save(model.state_dict(), Path(result_dir) / f"outcomes-{rank}.pt")
    finally:
        dist.destroy_process_group()


@pytest.mark.integration
@pytest.mark.parametrize("invalid_batch", [False, True])
def test_two_rank_ddp_handles_different_completed_game_counts_and_coordinated_validation(tmp_path, invalid_batch):
    mp.spawn(
        _distributed_outcome_worker,
        args=(str(tmp_path / "init"), str(tmp_path), invalid_batch), nprocs=2, join=True,
    )
    torch.testing.assert_close(
        torch.load(tmp_path / "outcomes-0.pt", weights_only=True),
        torch.load(tmp_path / "outcomes-1.pt", weights_only=True),
    )
