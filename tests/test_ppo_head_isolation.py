"""Loss isolation at the shared trunk and distributed optimizer boundary."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils._pytree import tree_flatten

from keisei.training.katago_ppo import KataGoPPOAlgorithm, KataGoPPOParams, KataGoRolloutBuffer
from keisei.training.models.katago_base import KataGoBaseModel, KataGoOutput
from keisei.training.value_adapter import MultiHeadValueAdapter


class TinySharedModel(KataGoBaseModel):
    def __init__(self) -> None:
        super().__init__()
        self.trunk = torch.nn.Linear(2, 4)
        self.policy = torch.nn.Linear(4, 3)
        self.value = torch.nn.Linear(4, 3)
        self.score = torch.nn.Linear(4, 1)

    def _forward_impl(self, obs: torch.Tensor) -> KataGoOutput:
        hidden = self.trunk(obs).tanh()
        return KataGoOutput(self.policy(hidden), self.value(hidden), self.score(hidden))


def _buffer(ppo: KataGoPPOAlgorithm, category: int = 0) -> KataGoRolloutBuffer:
    obs = torch.tensor([[1.0, -0.5], [-0.4, 0.7]])
    masks = torch.ones(2, 3, dtype=torch.bool)
    actions, log_probs, _ = ppo.select_actions(obs, masks)
    buffer = KataGoRolloutBuffer(2, (2,), 3)
    buffer.add(
        obs, actions, log_probs, torch.zeros(2), torch.tensor([0.0, 1.0]),
        torch.ones(2, dtype=torch.bool), torch.ones(2, dtype=torch.bool),
        masks, torch.full((2,), category), torch.zeros(2),
    )
    return buffer


@pytest.mark.parametrize("ignored_head", ["score", "value"])
def test_adapter_disconnects_unused_nan_head_from_shared_trunk(ignored_head):
    model = TinySharedModel()
    with torch.no_grad():
        getattr(model, ignored_head).weight.fill_(float("nan"))
    output = model(torch.ones(2, 2))
    adapter = MultiHeadValueAdapter(lambda_score=0.0 if ignored_head == "score" else 1.0)
    cats = torch.full((2,), -1 if ignored_head == "value" else 0)
    loss = adapter.compute_value_loss(
        output.value_logits, value_cats=cats,
        score_targets=torch.zeros(2), score_pred=output.score_lead,
    )
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(model.trunk.weight.grad).all()
    assert getattr(model, ignored_head).weight.grad is None


def test_ignored_nan_rows_do_not_enter_cross_entropy_backward():
    logits = torch.tensor([[float("nan")] * 3, [1.0, 0.0, -1.0]], requires_grad=True)
    adapter = MultiHeadValueAdapter(lambda_score=0.0)
    loss = adapter.compute_value_loss(
        logits, value_cats=torch.tensor([-1, 0]),
        score_targets=torch.zeros(2), score_pred=torch.zeros(2, 1),
    )
    loss.backward()
    assert torch.isfinite(logits.grad).all()
    assert logits.grad[0].eq(0).all()


@pytest.mark.parametrize("use_adapter", [False, True])
@pytest.mark.parametrize("ignored_head", ["score", "value"])
def test_ppo_unused_nan_head_cannot_poison_shared_parameters(use_adapter, ignored_head):
    model = TinySharedModel()
    with torch.no_grad():
        getattr(model, ignored_head).weight.fill_(float("nan"))
    params = KataGoPPOParams(
        epochs_per_batch=1, batch_size=2,
        lambda_score=0.0 if ignored_head == "score" else 1.0,
    )
    ppo = KataGoPPOAlgorithm(params, model)
    adapter = MultiHeadValueAdapter(lambda_score=params.lambda_score) if use_adapter else None
    buffer = _buffer(ppo, -1 if ignored_head == "value" else 0)
    metrics = ppo.update(buffer, torch.zeros(2), value_adapter=adapter)
    assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
    assert torch.isfinite(model.trunk.weight).all()
    assert torch.isfinite(model.trunk.weight.grad).all()
    assert getattr(model, ignored_head).weight.grad is None


@pytest.mark.parametrize("failure", ["value_loss", "score_loss", "gradient"])
def test_nonfinite_active_loss_or_gradient_stops_before_optimizer_step(monkeypatch, failure):
    model = TinySharedModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=2), model)
    buffer = _buffer(ppo)
    if failure == "gradient":
        model.score.weight.register_hook(lambda grad: torch.full_like(grad, float("nan")))
    else:
        with torch.no_grad():
            getattr(model, "value" if failure == "value_loss" else "score").weight.fill_(float("nan"))
    before = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    steps = []
    monkeypatch.setattr(ppo.optimizer, "step", lambda *args, **kwargs: steps.append(True))
    with pytest.raises(RuntimeError, match="[Nn]on.?finite"):
        ppo.update(buffer, torch.zeros(2))
    assert not steps
    for name, parameter in model.named_parameters():
        torch.testing.assert_close(parameter, before[name], equal_nan=True)


def test_katago_output_exposes_tensor_leaves_to_ddp_sink():
    output = TinySharedModel()(torch.ones(2, 2))
    leaves, _ = tree_flatten(output)
    assert len(leaves) == 3
    assert all(isinstance(leaf, torch.Tensor) for leaf in leaves)


def test_grad_scaler_recovers_from_overflow_and_only_counts_successful_updates(monkeypatch):
    model = TinySharedModel()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=2, batch_size=2), model)
    ppo.scaler = torch.amp.GradScaler("cpu", init_scale=128.0, growth_interval=2)
    scaler_state = ppo.scaler.state_dict()
    scaler_state["_growth_tracker"] = 1  # One prior successful step before this rollout.
    ppo.scaler.load_state_dict(scaler_state)
    buffer = _buffer(ppo)
    gradients_seen = 0

    def overflow_once(gradient):
        nonlocal gradients_seen
        gradients_seen += 1
        return torch.full_like(gradient, float("inf")) if gradients_seen == 1 else gradient

    model.score.weight.register_hook(overflow_once)
    original_step = ppo.optimizer.step
    steps = []

    def record_step(*args, **kwargs):
        steps.append(True)
        return original_step(*args, **kwargs)

    monkeypatch.setattr(ppo.optimizer, "step", record_step)
    metrics = ppo.update(buffer, torch.zeros(2))
    assert gradients_seen == 2
    assert len(steps) == 1
    assert ppo.scaler.get_scale() == 64.0
    assert ppo.scaler.state_dict()["_growth_tracker"] == 1
    assert metrics["gradient_norm"] > 0
    assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
    assert all(torch.isfinite(parameter).all() for parameter in model.parameters())


@pytest.mark.parametrize("device", ["cpu", "cuda"])
@pytest.mark.parametrize("compile_mode", [None, "default"])
def test_scaled_masked_entropy_keeps_policy_gradients_finite(monkeypatch, device, compile_mode):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    model = TinySharedModel()
    model.policy = torch.nn.Linear(4, 11259)
    with torch.no_grad():
        model.policy.weight.zero_()
        model.policy.bias.zero_()
    model.to(device)
    ppo = KataGoPPOAlgorithm(
        KataGoPPOParams(
            epochs_per_batch=1, batch_size=2, use_amp=True,
            compile_mode=compile_mode, lambda_value=0.0, lambda_score=0.0,
        ), model,
    )
    if device == "cpu":
        ppo.scaler = torch.amp.GradScaler("cpu")
    observations = torch.tensor([[1.0, -0.5], [-0.4, 0.7]], device=device)
    masks = torch.zeros(2, 11259, dtype=torch.bool, device=device)
    masks[:, :200] = True
    actions, log_probs, _ = ppo.select_actions(observations, masks)
    buffer = KataGoRolloutBuffer(2, (2,), 11259)
    buffer.add(
        observations.cpu(), actions.cpu(), log_probs.cpu(), torch.zeros(2),
        torch.tensor([0.0, 1.0]), torch.ones(2, dtype=torch.bool),
        torch.ones(2, dtype=torch.bool), masks.cpu(), torch.full((2,), -1), torch.zeros(2),
    )
    original_step = ppo.optimizer.step
    steps = []

    def record_step(*args, **kwargs):
        steps.append(True)
        return original_step(*args, **kwargs)

    monkeypatch.setattr(ppo.optimizer, "step", record_step)
    metrics = ppo.update(buffer, torch.zeros(2, device=device))
    assert len(steps) == 1
    assert ppo.scaler.get_scale() == 65536.0
    assert metrics["entropy"] == pytest.approx(torch.tensor(200.0).log().item(), abs=1e-5)
    assert model.policy.weight.grad is not None
    assert torch.isfinite(model.policy.weight.grad).all()
    assert model.policy.weight.grad[200:].eq(0).all()
    assert model.policy.weight[:200].ne(0).any()


def _distributed_worker(
    rank: int, init_path: str, result_dir: str, failure_head: str | None = None,
    schedule: str | None = None,
) -> None:
    torch.set_num_threads(1)
    dist.init_process_group(
        "gloo", init_method=f"file://{init_path}", rank=rank, world_size=2,
        timeout=timedelta(seconds=30),
    )
    try:
        torch.manual_seed(123)
        model = TinySharedModel()
        if failure_head is None:
            with torch.no_grad():
                model.score.weight.fill_(float("nan"))
        wrapped = DDP(model, find_unused_parameters=True)
        ppo = KataGoPPOAlgorithm(
            KataGoPPOParams(
                epochs_per_batch=2 if failure_head == "overflow" else 1, batch_size=2,
                lambda_score=0.0 if failure_head is None else 1.0,
            ),
            model, forward_model=wrapped,
        )
        if schedule is not None:
            buffer = _buffer(ppo)
            if schedule == "empty" and rank == 0:
                buffer.clear()
            elif schedule == "unequal" and rank == 1:
                data = buffer.flatten()
                buffer.add(
                    data["observations"], data["actions"], data["log_probs"], data["values"],
                    data["rewards"], data["dones"], data["terminated"], data["legal_masks"],
                    data["value_categories"], data["score_targets"],
                )
            with pytest.raises(ValueError, match="DDP requires"):
                ppo.update(buffer, torch.zeros(2))
            torch.save(True, Path(result_dir) / f"rejected-{rank}.pt")
            return
        if failure_head == "overflow":
            ppo.scaler = torch.amp.GradScaler("cpu", init_scale=128.0)
            buffer = _buffer(ppo)
            if rank == 1:
                gradients_seen = 0

                def overflow_once(gradient):
                    nonlocal gradients_seen
                    gradients_seen += 1
                    return torch.full_like(gradient, float("inf")) if gradients_seen == 1 else gradient

                model.score.weight.register_hook(overflow_once)
            original_step = ppo.optimizer.step
            steps = []

            def record_step(*args, **kwargs):
                steps.append(True)
                return original_step(*args, **kwargs)

            ppo.optimizer.step = record_step
            metrics = ppo.update(buffer, torch.zeros(2))
            assert len(steps) == 1
            assert ppo.scaler.get_scale() == 64.0
            assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
            torch.save(model.trunk.state_dict(), Path(result_dir) / f"rank-{rank}.pt")
            return
        if failure_head is not None:
            buffer = _buffer(ppo)
            if rank == 1:
                with torch.no_grad():
                    getattr(model, failure_head).weight.fill_(float("nan"))
            steps = []
            ppo.optimizer.step = lambda *args, **kwargs: steps.append(True)
            with pytest.raises(RuntimeError, match="Non-finite"):
                ppo.update(buffer, torch.zeros(2))
            assert not steps
            torch.save(True, Path(result_dir) / f"stopped-{rank}.pt")
            return
        for category in [0 if rank == 0 else -1, -1, 0]:
            metrics = ppo.update(_buffer(ppo, category), torch.zeros(2))
            assert all(torch.isfinite(torch.tensor(value)) for value in metrics.values())
            assert torch.isfinite(model.trunk.weight.grad).all()
            assert model.score.weight.grad is None
        torch.save(model.trunk.state_dict(), Path(result_dir) / f"rank-{rank}.pt")
    finally:
        dist.destroy_process_group()


@pytest.mark.integration
def test_two_rank_ddp_handles_disabled_and_rank_specific_ignored_heads(tmp_path):
    mp.spawn(
        _distributed_worker, args=(str(tmp_path / "init"), str(tmp_path)),
        nprocs=2, join=True,
    )
    torch.testing.assert_close(
        torch.load(tmp_path / "rank-0.pt", weights_only=True),
        torch.load(tmp_path / "rank-1.pt", weights_only=True),
    )


@pytest.mark.integration
def test_two_rank_ddp_recovers_together_from_rank_local_scaler_overflow(tmp_path):
    mp.spawn(
        _distributed_worker, args=(str(tmp_path / "init"), str(tmp_path), "overflow"),
        nprocs=2, join=True,
    )
    torch.testing.assert_close(
        torch.load(tmp_path / "rank-0.pt", weights_only=True),
        torch.load(tmp_path / "rank-1.pt", weights_only=True),
    )


@pytest.mark.integration
@pytest.mark.parametrize("failure_head", ["policy", "value", "score"])
def test_two_rank_ddp_nonfinite_head_stops_all_ranks_before_step(tmp_path, failure_head):
    mp.spawn(
        _distributed_worker, args=(str(tmp_path / "init"), str(tmp_path), failure_head),
        nprocs=2, join=True,
    )
    for rank in range(2):
        assert torch.load(tmp_path / f"stopped-{rank}.pt", weights_only=True)


@pytest.mark.integration
@pytest.mark.parametrize("schedule", ["unequal", "empty"])
def test_two_rank_ddp_rejects_incompatible_rollouts_before_update(tmp_path, schedule):
    mp.spawn(
        _distributed_worker, args=(str(tmp_path / "init"), str(tmp_path), None, schedule),
        nprocs=2, join=True,
    )
    for rank in range(2):
        assert torch.load(tmp_path / f"rejected-{rank}.pt", weights_only=True)
