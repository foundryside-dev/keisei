"""Completed-game critic targets and complete on-policy learner decisions."""

import dataclasses
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from keisei.training.katago_loop import KataGoTrainingLoop
from tests.test_katago_loop import _make_mock_katago_vecenv
from tests.test_learner_color_continuity import _config


def _capture_updates(loop):
    batches = []
    original = loop.ppo.update

    def capture(buffer, next_values, **kwargs):
        batches.append((
            {key: value.clone() for key, value in buffer.flatten().items()},
            kwargs.get("critic_batch"),
        ))
        return original(buffer, next_values, **kwargs)

    return batches, patch.object(loop.ppo, "update", side_effect=capture)


def test_completed_selfplay_game_supervises_both_players_earlier_positions(tmp_path):
    config = dataclasses.replace(_config(tmp_path, 50), league=None)
    env = _make_mock_katago_vecenv(alternate_players=True, terminate_at_step=3)
    loop = KataGoTrainingLoop(config, vecenv=env)
    batches, capture = _capture_updates(loop)

    with capture:
        loop.run(num_epochs=1, steps_per_epoch=3)

    actor, critic = batches[0]
    assert critic is not None, "Completed games must supply critic targets for earlier moves"
    torch.testing.assert_close(critic.observations, actor["observations"][[0, 2, 4]])
    assert critic.value_categories.tolist() == [0, 2, 0]


def test_critic_history_survives_rollout_cutoff_without_actor_replay(tmp_path):
    config = dataclasses.replace(_config(tmp_path, 50), league=None)
    env = _make_mock_katago_vecenv(alternate_players=True, terminate_at_step=3)
    loop = KataGoTrainingLoop(config, vecenv=env)
    batches, capture = _capture_updates(loop)

    with capture:
        loop.run(num_epochs=2, steps_per_epoch=2)

    first_actor, first_critic = batches[0]
    second_actor, completed_critic = batches[1]
    assert first_critic is None
    assert completed_critic is not None, "Unfinished critic history must survive PPO updates"
    expected = torch.cat((first_actor["observations"][[0, 2]], second_actor["observations"][[0]]))
    torch.testing.assert_close(completed_critic.observations, expected)
    assert completed_critic.value_categories.tolist() == [0, 2, 0]
    assert len(second_actor["observations"]) == 4  # Only this rollout's actor samples.


@pytest.mark.parametrize("reward", [1.0, 0.0, -1.0])
def test_opponent_terminal_response_reaches_ppo_before_boundary_update(tmp_path, reward):
    config = _config(tmp_path, 50)
    config = dataclasses.replace(config, league=dataclasses.replace(config.league, color_randomization=False))
    env = _make_mock_katago_vecenv(alternate_players=True, terminate_at_step=4)
    original_step = env.step.side_effect

    def step(actions, **kwargs):
        result = original_step(actions, **kwargs)
        if result.terminated[0]:
            result.rewards[0] = reward
        return result

    env.step.side_effect = step
    loop = KataGoTrainingLoop(config, vecenv=env)
    batches, capture = _capture_updates(loop)

    with capture:
        loop.run(num_epochs=1, steps_per_epoch=3)

    actor, critic = batches[0]
    terminal_rows = actor["terminated"].nonzero(as_tuple=True)[0]
    assert len(terminal_rows) == 1, "Outstanding opponent replies must resolve before optimization"
    assert actor["rewards"][terminal_rows].tolist() == [-reward]
    assert critic is not None
    expected_category = 2 if reward > 0 else 0 if reward < 0 else 1
    assert critic.value_categories.tolist() == [expected_category, expected_category]
    assert loop.global_step == 4


def test_boundary_completion_pauses_other_learner_lanes(tmp_path):
    env = _make_mock_katago_vecenv(alternate_players=True)
    loop = KataGoTrainingLoop(_config(tmp_path, 50), vecenv=env)
    batches, capture = _capture_updates(loop)

    with (
        capture,
        patch("keisei.training.katago_loop.np.random.randint", return_value=np.array([0, 1], dtype=np.uint8)),
    ):
        loop.run(num_epochs=1, steps_per_epoch=3)

    assert env.step.call_count == 4, "Finish the last learner decision before PPO updates"
    mask = env.step.call_args.kwargs["active_mask"]
    assert list(mask) == [True, False]
    actor, _ = batches[0]
    assert actor["env_ids"].tolist().count(0) == 2
    assert actor["env_ids"].tolist().count(1) == 1


@pytest.mark.integration
def test_native_boundary_truncation_bootstraps_terminal_board_and_preserves_paused_lane(tmp_path):
    from shogi_gym import VecEnv

    native = VecEnv(num_envs=2, max_ply=4, observation_mode="katago", action_mode="spatial")
    results = []
    terminal_values = []

    class RecordingEnv:
        def __getattr__(self, name):
            return getattr(native, name)

        def step(self, actions, **kwargs):
            result = native.step(actions, **kwargs)
            results.append(result)
            if result.truncated.any():
                with torch.no_grad():
                    output = loop.ppo.forward_model(torch.from_numpy(result.terminal_observations).to(loop.device))
                    terminal_values.append(loop.value_adapter.scalar_value_blended(
                        output.value_logits, output.score_lead,
                    ).cpu())
            return result

    env = RecordingEnv()
    env.step = MagicMock(side_effect=env.step)
    loop = KataGoTrainingLoop(_config(tmp_path, 50), vecenv=env)
    batches, capture = _capture_updates(loop)

    with (
        capture,
        patch("keisei.training.katago_loop.np.random.randint", side_effect=[
            np.array([0, 1], dtype=np.uint8), np.array([0], dtype=np.uint8),
        ]),
    ):
        loop.run(num_epochs=1, steps_per_epoch=3)

    assert env.step.call_args.kwargs["active_mask"] == [True, False]
    np.testing.assert_array_equal(results[-1].observations[1], results[-2].observations[1])
    np.testing.assert_array_equal(results[-1].legal_masks[1], results[-2].legal_masks[1])
    assert results[-1].current_players.tolist() == [0, 1]
    assert results[-1].truncated.tolist() == [True, False]
    actor, critic = batches[0]
    assert critic is None, "Truncated games do not have W/D/L outcomes"
    truncated_row = actor["dones"].bool() & ~actor["terminated"].bool()
    assert truncated_row.sum().item() == 1
    assert actor["env_ids"][truncated_row].tolist() == [0]
    # White made the terminal move, so the terminal board is Black-to-move,
    # matching the Black learner's frame. Use it rather than the reset board.
    torch.testing.assert_close(actor["next_value_override"][truncated_row], terminal_values[0][[0]])
