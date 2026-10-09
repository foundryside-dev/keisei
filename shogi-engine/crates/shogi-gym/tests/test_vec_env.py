"""Tests for VecEnv Python bindings."""
import numpy as np
import pytest
from shogi_gym import VecEnv


class TestVecEnvSpectatorData:
    def test_get_spectator_data_returns_list(self):
        """get_spectator_data() returns a list of dicts, one per env."""
        env = VecEnv(num_envs=3, max_ply=100)
        env.reset()
        data = env.get_spectator_data()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_get_spectator_data_dict_keys(self):
        """Each dict has the expected keys."""
        env = VecEnv(num_envs=1, max_ply=100)
        env.reset()
        data = env.get_spectator_data()
        d = data[0]
        expected_keys = {"board", "hands", "current_player", "ply", "is_over", "result", "winner", "sfen", "in_check", "move_history"}
        assert set(d.keys()) == expected_keys

    def test_get_spectator_data_startpos_values(self):
        """Verify startpos dict values are correct."""
        env = VecEnv(num_envs=1, max_ply=100)
        env.reset()
        d = env.get_spectator_data()[0]
        assert d["current_player"] == "black"
        assert d["ply"] == 0
        assert d["is_over"] is False
        assert d["result"] == "in_progress"
        assert d["winner"] is None
        assert d["in_check"] is False
        assert len(d["board"]) == 81
        assert "lnsgkgsnl" in d["sfen"].lower()

    def test_get_spectator_data_hands_structure(self):
        """Verify hands dict has correct structure."""
        env = VecEnv(num_envs=1, max_ply=100)
        env.reset()
        d = env.get_spectator_data()[0]
        assert "black" in d["hands"]
        assert "white" in d["hands"]
        assert "pawn" in d["hands"]["black"]
        assert d["hands"]["black"]["pawn"] == 0

    def test_get_spectator_data_after_step(self):
        """Verify dict updates after stepping."""
        env = VecEnv(num_envs=1, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        action = [int(np.where(masks[0])[0][0])]
        env.step(action)
        d = env.get_spectator_data()[0]
        assert d["ply"] == 1
        assert d["current_player"] == "white"

    def test_get_spectator_data_matches_spectator_env(self):
        """VecEnv and SpectatorEnv dicts should match (minus move_history)."""
        from shogi_gym import SpectatorEnv
        vec_env = VecEnv(num_envs=1, max_ply=100)
        spec_env = SpectatorEnv(max_ply=100)
        vec_env.reset()
        spec_env.reset()
        vec_d = vec_env.get_spectator_data()[0]
        spec_d = spec_env.to_dict()
        for key in ("board", "hands", "current_player", "ply", "is_over", "result", "sfen", "in_check"):
            assert vec_d[key] == spec_d[key], f"mismatch on key '{key}': {vec_d[key]} != {spec_d[key]}"


class TestVecEnvSfen:
    def test_get_sfens_returns_list(self):
        env = VecEnv(num_envs=3, max_ply=100)
        env.reset()
        sfens = env.get_sfens()
        assert isinstance(sfens, list)
        assert len(sfens) == 3
        for s in sfens:
            assert isinstance(s, str)

    def test_get_sfens_startpos(self):
        env = VecEnv(num_envs=2, max_ply=100)
        env.reset()
        sfens = env.get_sfens()
        assert sfens[0] == sfens[1]
        assert "lnsgkgsnl" in sfens[0].lower()

    def test_get_sfen_single(self):
        env = VecEnv(num_envs=2, max_ply=100)
        env.reset()
        sfens = env.get_sfens()
        for i in range(2):
            assert env.get_sfen(i) == sfens[i]

    def test_get_sfen_out_of_bounds(self):
        env = VecEnv(num_envs=2, max_ply=100)
        env.reset()
        with pytest.raises(IndexError):
            env.get_sfen(2)
        with pytest.raises(IndexError):
            env.get_sfen(100)

    def test_get_sfen_changes_after_step(self):
        env = VecEnv(num_envs=1, max_ply=100)
        result = env.reset()
        sfen_before = env.get_sfen(0)
        masks = np.asarray(result.legal_masks)
        action = [int(np.where(masks[0])[0][0])]
        env.step(action)
        sfen_after = env.get_sfen(0)
        assert sfen_before != sfen_after

    def test_get_sfen_matches_spectator_data(self):
        env = VecEnv(num_envs=2, max_ply=100)
        env.reset()
        sfens = env.get_sfens()
        data = env.get_spectator_data()
        for i in range(2):
            assert sfens[i] == data[i]["sfen"]


class TestVecEnvConstruction:
    def test_create(self):
        env = VecEnv(num_envs=4, max_ply=100)
        assert env.num_envs == 4
        assert env.action_space_size == 13_527
        assert env.observation_channels == 46

    def test_reset_shapes(self):
        env = VecEnv(num_envs=4, max_ply=100)
        result = env.reset()
        obs = np.asarray(result.observations)
        masks = np.asarray(result.legal_masks)
        assert obs.shape == (4, 46, 9, 9)
        assert obs.dtype == np.float32
        assert masks.shape == (4, 13_527)
        assert masks.dtype == np.bool_

    def test_reset_legal_masks_nonzero(self):
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        for i in range(2):
            assert masks[i].sum() > 0, f"env {i} has no legal moves at start"


class TestVecEnvEpisodeStats:
    def test_mean_episode_length_zero_before_completion(self):
        env = VecEnv(num_envs=1, max_ply=100)
        env.reset()
        assert env.mean_episode_length == 0.0

    def test_truncation_rate_zero_before_completion(self):
        env = VecEnv(num_envs=1, max_ply=100)
        env.reset()
        assert env.truncation_rate == 0.0

    def test_truncation_rate_after_max_ply(self):
        env = VecEnv(num_envs=2, max_ply=1)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]
        env.step(actions)
        assert env.episodes_completed == 2
        assert env.truncation_rate == 1.0

    def test_mean_episode_length_after_truncation(self):
        env = VecEnv(num_envs=2, max_ply=1)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]
        env.step(actions)
        assert env.mean_episode_length == 1.0

    def test_mean_episode_length_accumulates(self):
        env = VecEnv(num_envs=1, max_ply=1)
        result = env.reset()
        for _ in range(5):
            masks = np.asarray(result.legal_masks)
            action = [int(np.where(masks[0])[0][0])]
            result = env.step(action)
        assert env.episodes_completed == 5
        assert env.mean_episode_length == 1.0

    def test_reset_stats_clears_episode_length(self):
        env = VecEnv(num_envs=1, max_ply=1)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        action = [int(np.where(masks[0])[0][0])]
        env.step(action)
        assert env.mean_episode_length == 1.0
        env.reset_stats()
        assert env.mean_episode_length == 0.0
        assert env.truncation_rate == 0.0


class TestVecEnvStepping:
    def test_step_shapes(self):
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]

        step_result = env.step(actions)
        obs = np.asarray(step_result.observations)
        masks = np.asarray(step_result.legal_masks)
        rewards = np.asarray(step_result.rewards)
        terminated = np.asarray(step_result.terminated)
        truncated = np.asarray(step_result.truncated)

        assert obs.shape == (2, 46, 9, 9)
        assert masks.shape == (2, 13_527)
        assert rewards.shape == (2,)
        assert terminated.shape == (2,)
        assert truncated.shape == (2,)

    def test_step_wrong_num_actions(self):
        env = VecEnv(num_envs=2, max_ply=100)
        env.reset()
        with pytest.raises(ValueError):
            env.step([0])

    def test_step_illegal_action(self):
        env = VecEnv(num_envs=1, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        illegal_indices = np.where(~masks[0])[0]
        assert len(illegal_indices) > 0
        with pytest.raises(RuntimeError):
            env.step([int(illegal_indices[0])])

    def test_step_metadata(self):
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]

        step_result = env.step(actions)
        meta = step_result.step_metadata
        assert np.asarray(meta.captured_piece).shape == (2,)
        assert np.asarray(meta.termination_reason).shape == (2,)
        assert np.asarray(meta.ply_count).shape == (2,)

    def test_multi_step_no_crash(self):
        env = VecEnv(num_envs=4, max_ply=50)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        for _ in range(20):
            actions = []
            for i in range(4):
                legal = np.where(masks[i])[0]
                actions.append(int(legal[np.random.randint(len(legal))]))
            step_result = env.step(actions)
            masks = np.asarray(step_result.legal_masks)

    def test_autoreset_on_truncation(self):
        """Verify auto-reset produces valid initial state after truncation."""
        env = VecEnv(num_envs=1, max_ply=1)  # forces truncation after 1 move
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        action = [int(np.where(masks[0])[0][0])]
        step_result = env.step(action)
        # Should be truncated
        assert np.asarray(step_result.truncated)[0], "expected truncation at max_ply=1"
        # After auto-reset, legal masks should be the start-position masks (30 legal moves)
        assert np.asarray(step_result.legal_masks)[0].sum() == 30
        # Terminal observations should be non-zero (the game state before reset)
        term_obs = np.asarray(step_result.terminal_observations)
        assert term_obs.shape == (1, 46, 9, 9)
        assert term_obs[0].sum() != 0.0, "terminal obs should be non-zero"
        # Current player should be Black (just reset)
        assert np.asarray(step_result.current_players)[0] == 0, "reset game should start with Black"

    def test_terminal_observations_shape(self):
        """Verify terminal_observations has correct shape."""
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]
        step_result = env.step(actions)
        term_obs = np.asarray(step_result.terminal_observations)
        assert term_obs.shape == (2, 46, 9, 9)
        assert term_obs.dtype == np.float32

    def test_current_players_output(self):
        """Verify current_players is in the step result."""
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        actions = [int(np.where(masks[i])[0][0]) for i in range(2)]
        step_result = env.step(actions)
        players = np.asarray(step_result.current_players)
        assert players.shape == (2,)
        assert players.dtype == np.uint8
        # After first move, current player should be White (1)
        for p in players:
            assert p in (0, 1)

    def test_reward_values_in_range(self):
        """Rewards should only be -1.0, 0.0, or 1.0."""
        env = VecEnv(num_envs=4, max_ply=50)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        for _ in range(30):
            actions = []
            for i in range(4):
                legal = np.where(masks[i])[0]
                actions.append(int(legal[np.random.randint(len(legal))]))
            step_result = env.step(actions)
            rewards = np.asarray(step_result.rewards)
            for r in rewards:
                assert r in (-1.0, 0.0, 1.0), f"unexpected reward: {r}"
            masks = np.asarray(step_result.legal_masks)


class TestVecEnvMaskedStepping:
    @pytest.mark.parametrize("num_envs", [2, 64])
    @pytest.mark.parametrize("mode", ["default", "katago"])
    def test_only_active_lanes_advance(self, num_envs, mode):
        env = VecEnv(
            num_envs=num_envs, max_ply=100, observation_mode=mode,
            action_mode="spatial" if mode == "katago" else "default",
        )
        before = env.reset()
        before_obs = np.asarray(before.observations).copy()
        before_masks = np.asarray(before.legal_masks).copy()
        before_games = env.get_spectator_data()
        active = [i % 2 == 0 for i in range(num_envs)]
        actions = [int(np.flatnonzero(before_masks[i])[0]) if active[i] else -1 for i in range(num_envs)]

        result = env.step(actions, active_mask=active)
        after_games = env.get_spectator_data()

        assert np.asarray(result.observations).shape == before_obs.shape
        assert np.asarray(result.legal_masks).shape == before_masks.shape
        for i in range(num_envs):
            if active[i]:
                assert after_games[i]["ply"] == 1
                assert len(after_games[i]["move_history"]) == 1
                assert np.asarray(result.current_players)[i] == 1
            else:
                assert after_games[i] == before_games[i]
                np.testing.assert_array_equal(np.asarray(result.observations)[i], before_obs[i])
                np.testing.assert_array_equal(np.asarray(result.legal_masks)[i], before_masks[i])
                assert np.asarray(result.current_players)[i] == 0
        assert env.episodes_completed == 0

    def test_paused_lanes_do_not_repeat_previous_truncations(self):
        env = VecEnv(num_envs=2, max_ply=1)
        initial = env.reset()
        masks = np.asarray(initial.legal_masks)
        completed = env.step([int(np.flatnonzero(mask)[0]) for mask in masks])
        assert np.asarray(completed.truncated).all()
        before_games = env.get_spectator_data()

        result = env.step([-1, env.action_space_size * 10], active_mask=[False, False])

        assert env.get_spectator_data() == before_games
        assert env.episodes_completed == 2
        assert env.episodes_truncated == 2
        np.testing.assert_array_equal(result.observations, completed.observations)
        np.testing.assert_array_equal(result.legal_masks, completed.legal_masks)
        assert not np.asarray(result.terminated).any()
        assert not np.asarray(result.truncated).any()
        assert not np.asarray(result.rewards).any()
        np.testing.assert_array_equal(result.step_metadata.captured_piece, [255, 255])
        np.testing.assert_array_equal(result.step_metadata.termination_reason, [0, 0])
        np.testing.assert_array_equal(result.step_metadata.ply_count, [0, 0])

    @pytest.mark.parametrize("active", [[], [True], [True, True, True]])
    def test_wrong_mask_length_rejected_without_advancing_any_lane(self, active):
        env = VecEnv(num_envs=2, max_ply=100)
        masks = np.asarray(env.reset().legal_masks)
        actions = [int(np.flatnonzero(mask)[0]) for mask in masks]
        before = env.get_spectator_data()

        with pytest.raises(ValueError, match="active_mask"):
            env.step(actions, active_mask=active)

        assert env.get_spectator_data() == before
        assert env.episodes_completed == 0

    def test_invalid_active_action_rejects_the_entire_batch(self):
        env = VecEnv(num_envs=3, max_ply=1)
        masks = np.asarray(env.reset().legal_masks)
        before = env.get_spectator_data()
        actions = [int(np.flatnonzero(masks[0])[0]), -1, int(np.flatnonzero(~masks[2])[0])]

        with pytest.raises(RuntimeError, match="env 2"):
            env.step(actions, active_mask=[True, False, True])

        assert env.get_spectator_data() == before
        assert env.episodes_completed == 0

    def test_reset_updates_paused_players(self):
        env = VecEnv(num_envs=2, max_ply=100)
        masks = np.asarray(env.reset().legal_masks)
        advanced = env.step([int(np.flatnonzero(mask)[0]) for mask in masks])
        np.testing.assert_array_equal(advanced.current_players, [1, 1])
        reset = env.reset()

        result = env.step([-1, -1], active_mask=[False, False])

        np.testing.assert_array_equal(result.current_players, [0, 0])
        np.testing.assert_array_equal(result.observations, reset.observations)
        np.testing.assert_array_equal(result.legal_masks, reset.legal_masks)

    def test_all_active_mask_matches_unmasked_steps(self):
        ordinary = VecEnv(num_envs=2, max_ply=3)
        masked = VecEnv(num_envs=2, max_ply=3)
        masks = np.asarray(ordinary.reset().legal_masks)
        masked.reset()

        for _ in range(5):
            actions = [int(np.flatnonzero(mask)[0]) for mask in masks]
            expected = ordinary.step(actions)
            actual = masked.step(actions, active_mask=[True, True])
            for field in (
                "observations", "legal_masks", "rewards", "terminated", "truncated",
                "terminal_observations", "current_players",
            ):
                np.testing.assert_array_equal(getattr(actual, field), getattr(expected, field))
            assert masked.get_spectator_data() == ordinary.get_spectator_data()
            assert masked.episodes_completed == ordinary.episodes_completed
            masks = np.asarray(expected.legal_masks)


class TestVecEnvObservation:
    """Gap #9b: VecEnv observation consistency tests."""

    def test_observations_differ_between_envs_after_different_moves(self):
        """After different moves, observations should diverge."""
        env = VecEnv(num_envs=2, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        # Pick different actions for each env
        legal_0 = np.where(masks[0])[0]
        legal_1 = np.where(masks[1])[0]
        # Pick first legal move for env 0, last for env 1
        actions = [int(legal_0[0]), int(legal_1[-1])]
        if actions[0] != actions[1]:
            step_result = env.step(actions)
            obs = np.asarray(step_result.observations)
            assert not np.array_equal(obs[0], obs[1]), \
                "Different actions should lead to different observations"

    def test_observation_dtype_and_range(self):
        """Observations should be float32 and contain values in [0, 1] for binary planes."""
        env = VecEnv(num_envs=1, max_ply=100)
        result = env.reset()
        obs = np.asarray(result.observations)
        assert obs.dtype == np.float32
        # Piece presence planes (channels 0-27) should be binary
        piece_planes = obs[0, :28, :, :]
        unique_vals = np.unique(piece_planes)
        for v in unique_vals:
            assert v in (0.0, 1.0), f"Piece plane value {v} should be 0.0 or 1.0"

    def test_legal_masks_consistent_with_action_space(self):
        """Legal mask width should match action space size."""
        env = VecEnv(num_envs=3, max_ply=100)
        result = env.reset()
        masks = np.asarray(result.legal_masks)
        assert masks.shape == (3, env.action_space_size)

    def test_multiple_resets_produce_same_state(self):
        """Resetting the same VecEnv should produce identical initial states."""
        env = VecEnv(num_envs=2, max_ply=100)
        result1 = env.reset()
        obs1 = np.asarray(result1.observations).copy()
        masks1 = np.asarray(result1.legal_masks).copy()

        # Play some moves
        actions = [int(np.where(masks1[i])[0][0]) for i in range(2)]
        env.step(actions)

        # Reset again
        result2 = env.reset()
        obs2 = np.asarray(result2.observations)
        masks2 = np.asarray(result2.legal_masks)

        np.testing.assert_array_equal(obs1, obs2, "Reset should produce same observations")
        np.testing.assert_array_equal(masks1, masks2, "Reset should produce same masks")
