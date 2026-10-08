"""Exercise the rollout-to-optimizer trajectory boundary through real PPO."""

import pytest
import torch

import keisei.training.katago_ppo as module
from keisei.training.katago_ppo import KataGoPPOAlgorithm, KataGoPPOParams, KataGoRolloutBuffer
from tests.test_ppo_correctness import _model


@pytest.mark.parametrize("layout", ["dense", "partial", "permuted"])
def test_update_keeps_truncation_trace_and_environment_identity(monkeypatch, layout):
    model = _model()
    ppo = KataGoPPOAlgorithm(KataGoPPOParams(epochs_per_batch=1, batch_size=4), model)
    buffer = KataGoRolloutBuffer(3 if layout == "partial" else 2, (50, 9, 9), 11259)
    for step in range(2):
        env_ids = torch.tensor([1, 0]) if layout == "permuted" and step == 1 else torch.tensor([0, 1])
        reward = torch.tensor([float(step), 0.0])[env_ids]
        done = torch.tensor([True, bool(step)])[env_ids]
        terminal = torch.tensor([bool(step), bool(step)])[env_ids]
        override = torch.tensor([0.5 if step == 0 else float("nan"), float("nan")])[env_ids]
        buffer.add(
            torch.randn(2, 50, 9, 9), torch.zeros(2, dtype=torch.long),
            torch.full((2,), -9.0), torch.zeros(2), reward, done, terminal,
            torch.ones(2, 11259, dtype=torch.bool), torch.full((2,), -1), torch.zeros(2),
            env_ids=env_ids if layout != "dense" else None, next_value_override=override,
        )
    seen = []
    original = module.ppo_clip_loss

    def capture(new_log_probs, old_log_probs, advantages, clip_epsilon):
        seen.append(advantages.detach().clone())
        return original(new_log_probs, old_log_probs, advantages, clip_epsilon)

    monkeypatch.setattr(module, "ppo_clip_loss", capture)
    ppo.update(buffer, torch.zeros(buffer.num_envs))
    expected = torch.tensor([0.495, 0.0, 1.0, 0.0])
    expected = (expected - expected.mean()) / (expected.std() + 1e-8)
    torch.testing.assert_close(seen[0].sort().values, expected.sort().values)
