"""Public binding regressions for playable-state and observation contracts."""

import numpy as np
import pytest
from shogi_gym import SpatialActionMapper, SpectatorEnv, VecEnv

TWO_KINGS = "4k4/9/9/9/9/9/9/9/4K4"


@pytest.mark.parametrize(
    "sfen",
    [
        "8k/9/9/9/4P4/4P4/9/9/K8 b - 1",
        "8k/9/9/9/4p4/4p4/9/9/K8 w - 1",
        "P7k/9/9/9/9/9/9/9/K8 b - 1",
        "8k/9/9/9/9/9/9/9/K7l w - 1",
        "8k/4N4/9/9/9/9/9/9/K8 b - 1",
        "8k/9/9/9/9/9/9/4n4/K8 w - 1",
        f"{TWO_KINGS} b 19P 1",
        f"{TWO_KINGS} b 255P 1",
        f"{TWO_KINGS} b 256P 1",
        f"{TWO_KINGS} b PP 1",
        f"{TWO_KINGS} b 0P 1",
        f"{TWO_KINGS} b - 0",
        f"{TWO_KINGS} b - 4294967296",
        f"{TWO_KINGS} b -",
        f"{TWO_KINGS} b - 1 extra",
        "9/9/9/9/9/9/9/9/4K4 b - 1",
        "4k4/9/9/9/9/9/9/9/3KK4 b - 1",
        "4k4/4R4/9/9/9/9/9/9/4K4 b - 1",
        "4k4/9/9/9/4p4/9/9/9/4K4 b 18P 1",
        "4k4/9/9/9/4+r4/9/9/9/4K4 b 2R 1",
    ],
)
def test_invalid_playable_sfen_raises_value_error(sfen):
    with pytest.raises(ValueError, match="invalid SFEN"):
        SpectatorEnv.from_sfen(sfen)


@pytest.mark.parametrize(
    ("sfen", "result", "winner"),
    [
        ("Kr7/1g7/9/9/9/9/9/9/8k b - 1", "checkmate", "white"),
        (
            "Kr7/Lg6r/P1PPPPPPP/9/9/9/pppppppp1/8l/8k b B4S4N2Pb3g2l 1",
            "checkmate", "white",
        ),
        (
            "K8/Lg6r/P1PPPPPPP/8r/9/9/pppppppp1/8l/8k b B4S4N2Pb3g2l 1",
            "impasse", None,
        ),
        (
            "K8/Lg6r/P1PPPPPPP/8r/9/9/pppppppp1/8l/8k b 2B3G4S4N2P2l 1",
            "impasse", "black",
        ),
    ],
)
def test_loaded_terminal_states_expose_winner_and_no_actions(sfen, result, winner):
    env = SpectatorEnv.from_sfen(sfen)
    state = env.to_dict()
    assert env.is_over
    assert state["result"] == result
    assert state["winner"] == winner
    assert env.legal_actions() == []
    assert env.legal_moves_with_usi() == []
    with pytest.raises(RuntimeError, match="already over"):
        env.step(0)


def test_perpetual_check_on_last_ply_reports_the_nonchecking_winner():
    env = SpectatorEnv.from_sfen("5k3/9/4R4/9/9/9/9/9/4K4 b - 1", max_ply=12)
    for usi in ["5c4c", "4a5a", "4c5c", "5a4a"] * 3:
        env.step(dict((usi, action) for action, usi in env.legal_moves_with_usi())[usi])
    state = env.to_dict()
    assert state["ply"] == 12
    assert state["result"] == "perpetual_check"
    assert state["winner"] == "white"
    assert env.legal_actions() == []


@pytest.mark.parametrize("max_ply", [0, 65536])
def test_vector_ply_limit_must_fit_the_metadata_contract(max_ply):
    with pytest.raises(ValueError, match="between 1 and 65535"):
        VecEnv(num_envs=1, max_ply=max_ply)


def test_vector_ply_limit_accepts_the_u16_upper_boundary():
    assert VecEnv(num_envs=1, max_ply=65535).num_envs == 1


def test_spectator_ply_limit_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        SpectatorEnv(max_ply=0)
    with pytest.raises(ValueError, match="positive"):
        SpectatorEnv.from_sfen(f"{TWO_KINGS} b - 1", max_ply=0)


@pytest.mark.parametrize("is_white", [False, True])
@pytest.mark.parametrize("to_col", [3, 5])
def test_spatial_backward_knight_is_rejected_without_a_panic(is_white, to_col):
    source, destination = 4 * 9 + 4, 6 * 9 + to_col
    if is_white:
        source, destination = 80 - source, 80 - destination
    with pytest.raises(ValueError, match="Cannot encode"):
        SpatialActionMapper().encode_board_move(source, destination, False, is_white)


@pytest.mark.parametrize("observation_mode,channels", [("default", 46), ("katago", 50)])
@pytest.mark.parametrize("action_mode", ["default", "spatial"])
def test_spectator_observations_match_vector_features_through_repetition(
    observation_mode, channels, action_mode,
):
    spectator = SpectatorEnv(max_ply=100, action_mode=action_mode)
    vector = VecEnv(1, max_ply=100, observation_mode=observation_mode, action_mode=action_mode)
    reset = vector.reset()
    np.testing.assert_array_equal(
        spectator.get_observation(observation_mode=observation_mode), reset.observations[0],
    )
    for ply, usi in enumerate(["5i6h", "5a6b", "6h5i", "6b5a"] * 3, 1):
        action = dict((usi, action) for action, usi in spectator.legal_moves_with_usi())[usi]
        spectator.step(action)
        step = vector.step([action])
        expected = step.terminal_observations[0] if spectator.is_over else step.observations[0]
        actual = spectator.get_observation(observation_mode=observation_mode)
        assert actual.shape == (channels, 9, 9)
        np.testing.assert_array_equal(actual, expected)
        if observation_mode == "katago" and ply in [4, 8, 12]:
            assert np.all(actual[43 + ply // 4] == 1)
    assert spectator.to_dict()["result"] == "repetition"
    assert spectator.to_dict()["winner"] is None


def test_katago_observation_includes_check_for_the_white_perspective():
    env = SpectatorEnv.from_sfen("4k4/4R4/9/9/9/9/9/9/4K4 w - 1")
    assert not env.is_over
    assert env.legal_actions()
    observation = env.get_observation(observation_mode="katago")
    assert observation.shape == (50, 9, 9)
    assert np.all(observation[48] == 1)
    assert env.get_observation().shape == (46, 9, 9)
    with pytest.raises(ValueError, match="Unknown observation_mode"):
        env.get_observation(observation_mode="unsupported")


@pytest.mark.parametrize("action_mode", ["default", "spatial"])
@pytest.mark.parametrize("piece", ["P", "L", "N"])
@pytest.mark.parametrize("white", [False, True])
def test_promoted_piece_on_last_rank_has_no_second_promotion_marker(action_mode, piece, white):
    if white:
        sfen = f"8k/9/9/9/9/9/9/4+{piece.lower()}4/K8 w - 1"
        usi, expected = "5h5i", f"+{piece}-5i"
    else:
        sfen = f"8k/4+{piece}4/9/9/9/9/9/9/K8 b - 1"
        usi, expected = "5b5a", f"+{piece}-5a"
    env = SpectatorEnv.from_sfen(sfen, action_mode=action_mode)
    action = next(action for action, move in env.legal_moves_with_usi() if move == usi)
    state = env.step(action)
    assert state["move_history"][-1]["notation"] == expected
