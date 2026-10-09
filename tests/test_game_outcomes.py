"""Completed-game value targets retain every selected mover's perspective."""

import numpy as np
import pytest
import torch


def _tracker(num_envs):
    from keisei.training.outcomes import GameOutcomeTracker

    return GameOutcomeTracker(num_envs)


def _resolve(tracker, rewards, terminated, truncated, players):
    tracker.resolve(
        torch.tensor(rewards), torch.tensor(terminated), torch.tensor(truncated),
        np.asarray(players),
    )


@pytest.mark.parametrize("reward,expected", [
    (1.0, [0, 2, 0]), (-1.0, [2, 0, 2]), (0.0, [1, 1, 1]),
])
def test_completed_game_labels_all_movers_from_their_own_perspective(reward, expected):
    tracker = _tracker(1)
    for step, player in enumerate([0, 1, 0]):
        tracker.record(torch.tensor([[float(step)]]), np.array([player]))
        _resolve(tracker, [reward if step == 2 else 0.0], [step == 2], [False], [player])

    batch = tracker.pop_completed()
    assert batch is not None
    assert batch.observations[:, 0].tolist() == [0.0, 1.0, 2.0]
    assert batch.value_categories.tolist() == expected
    assert tracker.pop_completed() is None


def test_pop_completed_preserves_unfinished_game_across_rollout_boundaries():
    tracker = _tracker(1)
    tracker.record(torch.tensor([[1.0]]), np.array([0]))
    _resolve(tracker, [0.0], [False], [False], [0])
    assert tracker.pop_completed() is None

    tracker.record(torch.tensor([[2.0]]), np.array([1]))
    _resolve(tracker, [1.0], [True], [False], [1])
    batch = tracker.pop_completed()
    assert batch is not None
    assert batch.observations[:, 0].tolist() == [1.0, 2.0]
    assert batch.value_categories.tolist() == [2, 0]


def test_truncation_discards_only_ended_lane_before_auto_reset():
    tracker = _tracker(2)
    tracker.record(torch.tensor([[10.0], [20.0]]), np.array([0, 1]))
    _resolve(tracker, [0.0, 0.0], [False, False], [True, False], [0, 1])
    assert tracker.pop_completed() is None

    tracker.record(torch.tensor([[11.0], [21.0]]), np.array([0, 0]))
    _resolve(tracker, [1.0, 1.0], [True, True], [False, False], [0, 0])
    batch = tracker.pop_completed()
    assert batch is not None
    assert batch.observations[:, 0].tolist() == [11.0, 20.0, 21.0]
    assert batch.value_categories.tolist() == [0, 2, 0]


def test_league_records_only_learner_moves_and_labels_opponent_terminal_win():
    tracker = _tracker(2)
    tracker.record(
        torch.tensor([[10.0], [20.0]]), np.array([0, 1]),
        mask=torch.tensor([True, False]),
    )
    _resolve(tracker, [0.0, 0.0], [False, False], [False, False], [0, 1])
    tracker.record(
        torch.tensor([[11.0], [21.0]]), np.array([1, 0]),
        mask=torch.tensor([False, True]),
    )
    _resolve(tracker, [1.0, -1.0], [True, True], [False, False], [1, 0])
    batch = tracker.pop_completed()
    assert batch is not None
    assert batch.observations[:, 0].tolist() == [10.0, 21.0]
    assert batch.value_categories.tolist() == [2, 2]


def test_record_owns_detached_cpu_snapshot():
    tracker = _tracker(1)
    observations = torch.tensor([[3.0, 4.0]], requires_grad=True)
    tracker.record(observations, np.array([0]))
    with torch.no_grad():
        observations.fill_(99.0)
    _resolve(tracker, [1.0], [True], [False], [0])
    batch = tracker.pop_completed()
    assert batch is not None
    torch.testing.assert_close(batch.observations, torch.tensor([[3.0, 4.0]]))
    assert batch.observations.device.type == "cpu"
    assert not batch.observations.requires_grad
    assert batch.value_categories.dtype == torch.long


def test_ended_lane_does_not_keep_previous_episode_observations():
    tracker = _tracker(1)
    for observation, reward in [(1.0, 1.0), (2.0, -1.0)]:
        tracker.record(torch.tensor([[observation]]), np.array([0]))
        _resolve(tracker, [reward], [True], [False], [0])
        batch = tracker.pop_completed()
        assert batch is not None
        assert batch.observations[:, 0].tolist() == [observation]
        assert batch.value_categories.tolist() == [0 if reward > 0 else 2]


@pytest.mark.parametrize("invalid", ["observations", "players", "mask"])
def test_record_rejects_misaligned_lanes(invalid):
    tracker = _tracker(2)
    observations = torch.zeros(1 if invalid == "observations" else 2, 3)
    players = np.array([0] if invalid == "players" else [0, 1])
    mask = torch.ones(1 if invalid == "mask" else 2, dtype=torch.bool)
    with pytest.raises(ValueError):
        tracker.record(observations, players, mask)


def test_resolve_rejects_nonfinite_terminal_reward_without_losing_history():
    tracker = _tracker(1)
    tracker.record(torch.tensor([[1.0]]), np.array([0]))
    with pytest.raises(ValueError, match="finite"):
        _resolve(tracker, [float("nan")], [True], [False], [0])
    _resolve(tracker, [1.0], [True], [False], [0])
    assert tracker.pop_completed().observations.shape[0] == 1
