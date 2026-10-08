"""Regression tests for perspective, episode boundaries and behavior policies."""
from __future__ import annotations

import math

import pytest
import torch

from keisei.training.gae import (
    compute_gae,
    compute_gae_gpu,
    compute_gae_padded,
    compute_gae_padded_gpu,
)
from keisei.training.katago_ppo import KataGoPPOAlgorithm, KataGoPPOParams, KataGoRolloutBuffer
from keisei.training.models.se_resnet import SEResNetModel, SEResNetParams


def _model():
    return SEResNetModel(SEResNetParams(
        num_blocks=2, channels=32, se_reduction=8, global_pool_channels=16,
        policy_channels=8, value_fc_size=32, score_fc_size=16,
    ))


def _gae(function, *, truncated=False, alternating=False):
    kwargs = dict(
        rewards=torch.tensor([[0.0], [1.0]]), values=torch.zeros(2, 1),
        terminated=torch.tensor([[False], [True]]), next_value=torch.zeros(1),
        gamma=0.99, lam=0.95,
        next_value_override=torch.tensor([[0.5 if truncated else 0.0], [float('nan')]]),
        trace_dones=torch.tensor([[truncated], [True]]),
        trace_sign=-1.0 if alternating else 1.0,
    )
    if function in (compute_gae_padded, compute_gae_padded_gpu):
        kwargs['next_values'] = kwargs.pop('next_value')
        kwargs['lengths'] = torch.tensor([2])
    return function(**kwargs).squeeze(1)


@pytest.mark.parametrize('function', [compute_gae, compute_gae_gpu, compute_gae_padded, compute_gae_padded_gpu])
def test_alternating_gae_penalizes_move_before_opponent_win(function):
    assert torch.allclose(_gae(function, alternating=True), torch.tensor([-0.9405, 1.0]))


@pytest.mark.parametrize('function', [compute_gae, compute_gae_gpu, compute_gae_padded, compute_gae_padded_gpu])
def test_truncation_bootstraps_without_new_game_advantage(function):
    assert torch.allclose(_gae(function, truncated=True), torch.tensor([0.495, 1.0]))


def test_bf16_collection_logs_actual_behavior_probability():
    model = _model()
    with torch.no_grad():
        model.policy_conv2.weight.zero_()
        model.policy_conv2.bias.zero_()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(use_amp=True), model)
    masks = torch.zeros(4, 11259, dtype=torch.bool)
    masks[:, :200] = True
    _, log_probs, _ = ppo.select_actions(torch.randn(4, 50, 9, 9), masks)
    assert log_probs.dtype == torch.float32
    assert torch.allclose(log_probs, torch.full((4,), -math.log(200)), atol=1e-6)


@pytest.mark.parametrize("compile_mode", [None, "default"])
def test_update_uses_same_policy_before_first_optimizer_step(monkeypatch, compile_mode):
    import keisei.training.katago_ppo as module

    torch.manual_seed(42)
    model = _model()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=8, compile_mode=compile_mode), model)
    obs = torch.randn(8, 50, 9, 9)
    masks = torch.ones(8, 11259, dtype=torch.bool)
    actions, log_probs, values = ppo.select_actions(obs, masks)
    buffer = KataGoRolloutBuffer(8, (50, 9, 9), 11259)
    buffer.add(obs, actions, log_probs, values, torch.arange(8).float() % 2,
               torch.ones(8, dtype=torch.bool), torch.ones(8, dtype=torch.bool),
               masks, torch.zeros(8, dtype=torch.long), torch.zeros(8))
    ratios = []
    original = module.ppo_clip_loss

    def capture(new_log_probs, old_log_probs, advantages, clip_epsilon):
        ratios.append((new_log_probs - old_log_probs).exp().detach())
        return original(new_log_probs, old_log_probs, advantages, clip_epsilon)

    monkeypatch.setattr(module, 'ppo_clip_loss', capture)
    ppo.update(buffer, torch.zeros(8))
    assert len(ratios) == 1
    assert torch.allclose(ratios[0], torch.ones(8), atol=1e-5)
    assert model.policy_conv2.weight.grad is not None
    assert model.policy_conv2.weight.grad.abs().sum() > 0


def _add(buffer, *, env_ids=None, override=None, values=None):
    buffer.add(
        torch.zeros(1, 1), torch.zeros(1, dtype=torch.long), torch.zeros(1),
        torch.zeros(1) if values is None else values, torch.zeros(1),
        torch.zeros(1, dtype=torch.bool), torch.zeros(1, dtype=torch.bool),
        torch.ones(1, 2, dtype=torch.bool), torch.full((1,), -1), torch.zeros(1),
        env_ids=env_ids, next_value_override=override,
    )


def test_buffer_clear_resets_trajectory_schema():
    buffer = KataGoRolloutBuffer(1, (1,), 2)
    _add(buffer, env_ids=torch.zeros(1, dtype=torch.long))
    buffer.clear()
    _add(buffer)
    assert 'env_ids' not in buffer.flatten()


def test_buffer_reused_late_override_survives():
    buffer = KataGoRolloutBuffer(1, (1,), 2)
    _add(buffer, override=torch.tensor([0.7]))
    buffer.clear()
    _add(buffer)
    _add(buffer, override=torch.tensor([0.3]))
    assert 'next_value_override' in buffer.flatten()
    override = buffer.flatten()['next_value_override']
    assert torch.isnan(override[0])
    assert override[1].item() == pytest.approx(0.3)


def test_buffer_rejects_broadcasted_values():
    buffer = KataGoRolloutBuffer(1, (1,), 2)
    with pytest.raises(ValueError, match='values.*shape'):
        _add(buffer, values=torch.tensor(0.0))


@pytest.mark.parametrize('name,value', [
    ('learning_rate', float('nan')), ('grad_clip', float('inf')),
    ('lambda_policy', -1.0), ('lambda_entropy', -0.1),
    ('lambda_value', float('nan')), ('lambda_score', -0.1),
    ('score_normalization', 0.0), ('score_blend_alpha', 1.1),
    ('entropy_decay_epochs', -1),
])
def test_invalid_ppo_parameters_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        KataGoPPOParams(**{name: value})


def test_disabled_auxiliary_head_does_not_poison_loss():
    from keisei.training.value_adapter import MultiHeadValueAdapter

    logits = torch.zeros(2, 3, requires_grad=True)
    scores = torch.full((2, 1), float('nan'), requires_grad=True)
    adapter = MultiHeadValueAdapter(lambda_value=1.0, lambda_score=0.0)
    loss = adapter.compute_value_loss(logits, value_cats=torch.tensor([0, 2]),
                                      score_targets=torch.zeros(2), score_pred=scores)
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(logits.grad).all()
    assert scores.grad is None or scores.grad.eq(0).all()


def test_ignored_value_labels_have_finite_zero_loss():
    from keisei.training.value_adapter import MultiHeadValueAdapter

    logits = torch.full((2, 3), float('nan'), requires_grad=True)
    adapter = MultiHeadValueAdapter(lambda_score=0.0)
    loss = adapter.compute_value_loss(logits, value_cats=torch.tensor([-1, -1]),
                                      score_targets=torch.zeros(2), score_pred=torch.zeros(2, 1))
    assert loss.item() == 0.0
    assert not loss.requires_grad
    assert logits.grad is None


def test_alternating_bootstrap_survives_buffer_reuse():
    buffer = KataGoRolloutBuffer(1, (1,), 2)
    for _ in range(2):
        _add(buffer, values=torch.tensor([0.2]))
        _add(buffer, values=torch.tensor([0.3]))
        buffer.fill_alternating_perspective_overrides()
        assert 'next_value_override' in buffer.flatten()
        assert buffer.flatten()['next_value_override'][0].item() == pytest.approx(-0.3)
        buffer.clear()


def test_gae_rejects_scalar_bootstrap_for_multiple_environments():
    with pytest.raises(ValueError, match='next_value.*shape'):
        compute_gae(torch.zeros(2, 3), torch.zeros(2, 3), torch.zeros(2, 3),
                    torch.tensor(0.0), gamma=0.99, lam=0.95)
