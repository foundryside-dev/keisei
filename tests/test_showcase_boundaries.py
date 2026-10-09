"""Spectator engines and model inference share complete state contracts."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from keisei.db import _connect, init_db
from keisei.db.showcase import claim_next_match, queue_match
from keisei.showcase.inference import ModelCache, run_inference
from keisei.showcase.runner import ShowcaseRunner
from keisei.training.model_registry import build_model, get_obs_channels


@pytest.mark.parametrize("channels", [46, 49, 51])
def test_katago_inference_rejects_fabricated_or_truncated_features(channels: int) -> None:
    model = MagicMock()
    with pytest.raises(ValueError, match="observation"):
        run_inference(model, np.zeros((channels, 9, 9), dtype=np.float32), "se_resnet")
    model.assert_not_called()


def test_showcase_cache_refreshes_atomically_replaced_checkpoint(tmp_path: Path) -> None:
    params = {"hidden_sizes": [4]}
    path = tmp_path / "weights.pt"
    model = build_model("mlp", params)
    torch.save(model.state_dict(), path)
    cache = ModelCache()
    first = cache.get_or_load("1", str(path), "mlp", params)
    with torch.no_grad():
        next(model.parameters()).add_(1)
    replacement = tmp_path / "replacement.pt"
    torch.save(model.state_dict(), replacement)
    replacement.replace(path)
    second = cache.get_or_load("1", str(path), "mlp", params)
    assert second is not first
    assert torch.equal(next(second.parameters()), next(model.parameters()))


@pytest.mark.parametrize(
    ("result", "winner"), [("checkmate", "black"), ("perpetual_check", "white"), ("impasse", "black"), ("impasse", None)]
)
def test_runner_preserves_decisive_engine_outcome_even_on_last_ply(tmp_path: Path, result: str, winner: str | None) -> None:
    db = str(tmp_path / "outcome.db")
    init_db(db)
    queue_match(db, "1", "2", "fast")
    match = claim_next_match(db)
    runner = ShowcaseRunner(db)
    env = MagicMock()
    env.is_over = False
    env.reset.return_value = {"current_player": "black", "ply": 0}
    env.get_observation.return_value = np.zeros((get_obs_channels("mlp"), 9, 9), dtype=np.float32)
    env.legal_actions.return_value = [0]
    env.legal_moves_with_usi.return_value = [(0, "7g7f")]
    env.step.return_value = {
        "current_player": "white",
        "ply": 1,
        "move_history": [],
        "board": [],
        "hands": {},
        "result": result,
        "winner": winner,
    }
    entry = {"elo_rating": 1500, "display_name": "M"}
    with (
        patch.object(runner, "_create_env", return_value=env),
        patch.object(runner, "_load_models", return_value=(None, None, "mlp", "mlp", entry, entry)),
        patch(
            "keisei.showcase.runner.run_inference_with_evaluation",
            return_value=(
                np.zeros(13527),
                0.5,
                {
                    "version": 1,
                    "kind": "outcome_score",
                    "score": 0.5,
                    "player": "black",
                    "position_ply": 0,
                    "source": {"architecture": "mlp", "contract": "scalar"},
                },
            ),
        ) as inference,
        patch("keisei.showcase.runner.MAX_PLY", 1),
        patch.object(runner, "_get_delay", return_value=0),
    ):
        runner._run_game(match)
    inference.assert_called_once_with(
        None, env.get_observation.return_value, "mlp", player="black", position_ply=0,
    )
    with _connect(db) as conn:
        status = conn.execute("SELECT status FROM showcase_games").fetchone()["status"]
    assert status == (f"{winner}_win" if winner else "draw")


def test_runner_heartbeat_continues_while_game_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "heartbeat.db")
    init_db(db)
    queue_match(db, "1", "2", "normal")
    runner = ShowcaseRunner(db, auto_showcase_enabled=False)
    heartbeat = threading.Event()
    calls = []

    def write() -> None:
        calls.append(True)
        if len(calls) > 1:
            heartbeat.set()

    def game(match: dict) -> None:
        try:
            assert heartbeat.wait(1), "heartbeat stopped while a game was running"
        finally:
            runner.stop()

    monkeypatch.setattr("keisei.showcase.runner.HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr("keisei.showcase.runner.enforce_cpu_only", lambda _: None)
    monkeypatch.setattr(runner, "_write_heartbeat", write)
    monkeypatch.setattr(runner, "_run_game", game)
    runner.run()
    assert heartbeat.is_set()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nonfinite_model_output_is_rejected_before_sampling(bad: float) -> None:
    model = MagicMock(return_value=(torch.full((1, 13527), bad), torch.zeros((1, 1))))
    with pytest.raises(ValueError, match="Non-finite model output"):
        run_inference(model, np.zeros((50, 9, 9), dtype=np.float32), "mlp")


def test_fresh_heartbeat_of_dead_runner_does_not_block_crash_recovery(tmp_path: Path) -> None:
    from keisei.db.showcase import cleanup_orphaned_games, create_showcase_game, read_queue, write_heartbeat

    db = str(tmp_path / "crash.db")
    init_db(db)
    qid = queue_match(db, "1", "2", "normal")
    claim_next_match(db)
    create_showcase_game(
        db, queue_id=qid, entry_id_black="1", entry_id_white="2", elo_black=1500, elo_white=1500, name_black="A", name_white="B"
    )
    write_heartbeat(db, pid=2**30)
    assert cleanup_orphaned_games(db) == 1
    assert read_queue(db) == []
