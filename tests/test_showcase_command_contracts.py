"""Showcase commands preserve connection, identity and queue state contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from keisei.db import _connect, init_db
from keisei.db.showcase import cancel_match, claim_next_match, queue_match, read_queue
from keisei.server.app import _handle_cancel, _handle_match_request, _handle_speed_change, _receive_commands


class Socket:
    def __init__(self, messages: list[object] | None = None) -> None:
        self.sent: list[dict] = []
        self.messages = iter(messages or [])

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def receive_text(self) -> str:
        try:
            return json.dumps(next(self.messages))
        except StopIteration:
            raise WebSocketDisconnect() from None


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "commands.db")
    init_db(path)
    with _connect(path) as conn:
        for i in (1, 2):
            conn.execute(
                "INSERT INTO league_entries (id, display_name, architecture, model_params, "
                "checkpoint_path, elo_rating, status, created_epoch) "
                "VALUES (?, ?, 'resnet', '{}', '/tmp/weights.pt', 1500, 'active', 0)",
                (i, str(i)),
            )
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_id", [999, None, True, 1.5, "nope"])
async def test_speed_errors_are_correlated_and_do_not_ack_stale_ids(db: str, queue_id: object) -> None:
    ws = Socket()
    await _handle_speed_change(ws, asyncio.Lock(), db, {"queue_id": queue_id, "speed": "fast", "request_id": "speed-1"})
    assert ws.sent[-1]["type"] == "showcase_error"
    assert ws.sent[-1]["request_id"] == "speed-1"


@pytest.mark.asyncio
async def test_speed_and_cancel_ack_only_applied_changes(db: str) -> None:
    qid = queue_match(db, "1", "2", "normal")
    ws = Socket()
    await _handle_speed_change(ws, asyncio.Lock(), db, {"queue_id": qid, "speed": "fast", "request_id": "speed"})
    assert ws.sent[-1] == {"type": "showcase_speed_changed", "queue_id": qid, "speed": "fast", "request_id": "speed"}
    await _handle_cancel(ws, asyncio.Lock(), db, {"queue_id": qid, "request_id": "cancel"})
    assert ws.sent[-1]["request_id"] == "cancel"
    await _handle_speed_change(ws, asyncio.Lock(), db, {"queue_id": qid, "speed": "slow", "request_id": "late"})
    assert ws.sent[-1]["type"] == "showcase_error"
    await _handle_cancel(ws, asyncio.Lock(), db, {"queue_id": qid, "request_id": "twice"})
    assert ws.sent[-1]["type"] == "showcase_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [None, {}, [], True, "999", 1.5])
async def test_match_request_rejects_invalid_or_unknown_entry(db: str, entry: object) -> None:
    ws = Socket()
    await _handle_match_request(ws, asyncio.Lock(), db, {"entry_id_1": entry, "entry_id_2": "2", "speed": "normal", "request_id": "match"})
    assert ws.sent[-1]["type"] == "showcase_error"
    assert ws.sent[-1]["request_id"] == "match"
    assert read_queue(db) == []


@pytest.mark.asyncio
async def test_bad_command_shapes_do_not_disconnect_following_valid_request(db: str) -> None:
    ws = Socket(
        [
            None,
            [],
            {"type": "change_showcase_speed", "speed": [], "queue_id": 1, "request_id": "bad"},
            {"type": "request_showcase_match", "entry_id_1": "1", "entry_id_2": "2", "request_id": "good"},
        ]
    )
    with pytest.raises(WebSocketDisconnect):
        await _receive_commands(ws, asyncio.Lock(), db)
    assert ws.sent[-1]["type"] == "showcase_match_queued"
    assert ws.sent[-1]["request_id"] == "good"
    assert ws.sent[-1]["queue_id"] == read_queue(db)[0]["id"]


def test_claim_with_running_game_leaves_pending_match_queued(db: str) -> None:
    queue_match(db, "1", "2", "normal")
    assert claim_next_match(db) is not None
    waiting = queue_match(db, "1", "2", "normal")
    assert claim_next_match(db) is None
    assert read_queue(db)[-1]["id"] == waiting
    assert read_queue(db)[-1]["status"] == "pending"


def test_cancel_reports_whether_pending_match_existed(db: str) -> None:
    qid = queue_match(db, "1", "2", "normal")
    assert cancel_match(db, qid) is True
    assert cancel_match(db, qid) is False


def test_queue_depth_limit_is_atomic(db: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def insert(_: int) -> int | None:
        try:
            return queue_match(db, "1", "2", "normal", max_pending=5, validate_entries=True)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(insert, range(12)))
    assert sum(result is not None for result in results) == 5
    assert len(read_queue(db)) == 5


@pytest.mark.asyncio
async def test_showcase_status_pushes_same_length_speed_changes(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.db.showcase import update_queue_speed
    from keisei.server.app import _poll_showcase

    qid = queue_match(db, "1", "2", "normal")
    ws = Socket()

    async def send(data: dict) -> None:
        ws.sent.append(data)
        if data["type"] == "showcase_status":
            if data["queue"][0]["speed"] == "normal":
                update_queue_speed(db, qid, "fast")
            else:
                raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.SHOWCASE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_showcase(ws, asyncio.Lock(), db), timeout=1)
    assert ws.sent[-1]["queue"][0]["speed"] == "fast"


@pytest.mark.asyncio
async def test_new_game_is_pushed_before_first_move(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.db.showcase import create_showcase_game
    from keisei.server.app import _poll_showcase

    qid = queue_match(db, "1", "2", "normal")
    claim_next_match(db)
    gid = create_showcase_game(
        db, queue_id=qid, entry_id_black="1", entry_id_white="2", elo_black=1500, elo_white=1500, name_black="A", name_white="B"
    )
    ws = Socket()

    async def send(data: dict) -> None:
        ws.sent.append(data)
        if data["type"] == "showcase_update":
            raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.SHOWCASE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_showcase(ws, asyncio.Lock(), db), timeout=1)
    assert ws.sent[-1]["game"]["id"] == gid
    assert ws.sent[-1]["new_moves"] == []


@pytest.mark.asyncio
async def test_league_pushes_same_id_rating_and_library_metadata(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.server.app import _poll_and_push

    ws = Socket()

    async def send(data: dict) -> None:
        ws.sent.append(data)
        if data["type"] == "init":
            assert data["league_totals"]["games"] == 0
            assert data["entry_records"] == []
            with _connect(db) as conn:
                conn.execute("UPDATE league_entries SET elo_rating=1800 WHERE id=1")
        if data["type"] == "league_update":
            raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.POLL_INTERVAL_S", 0.001)
    monkeypatch.setattr("keisei.server.app.LEAGUE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_and_push(ws, asyncio.Lock(), db), timeout=1)
    assert next(e for e in ws.sent[-1]["entries"] if e["id"] == 1)["elo_rating"] == 1800


@pytest.mark.asyncio
async def test_completion_sends_final_result_and_moves_before_idle_status(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.db.showcase import create_showcase_game, mark_game_completed, write_showcase_move
    from keisei.server.app import _poll_showcase

    qid = queue_match(db, "1", "2", "normal")
    claim_next_match(db)
    gid = create_showcase_game(
        db, queue_id=qid, entry_id_black="1", entry_id_white="2", elo_black=1500, elo_white=1500, name_black="A", name_white="B"
    )
    ws = Socket()
    finished = False

    async def send(data: dict) -> None:
        nonlocal finished
        ws.sent.append(data)
        if data["type"] == "showcase_update" and not finished:
            finished = True
            write_showcase_move(
                db,
                game_id=gid,
                ply=1,
                action_index=0,
                usi_notation="7g7f",
                board_json="[]",
                hands_json="{}",
                current_player="white",
                in_check=False,
                value_estimate=0.5,
                top_candidates="[]",
                move_time_ms=1,
            )
            mark_game_completed(db, gid, "black_win", 1)
        elif data["type"] == "showcase_status" and data["active_game_id"] is None:
            raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.SHOWCASE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_showcase(ws, asyncio.Lock(), db), timeout=1)
    updates = [m for m in ws.sent if m["type"] == "showcase_update"]
    assert updates[-1]["game"]["status"] == "black_win"
    assert updates[-1]["new_moves"][0]["ply"] == 1
    assert ws.sent.index(updates[-1]) < len(ws.sent) - 1


@pytest.mark.asyncio
async def test_style_profile_refresh_pushes_without_new_league_result(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.server.app import _poll_and_push

    ws = Socket()
    profile = {"checkpoint_id": 1, "profile_status": "ready", "primary_style": "balanced", "confidence": 0.1}
    monkeypatch.setattr("keisei.server.app.read_style_profiles", lambda _: [dict(profile)])

    async def send(data: dict) -> None:
        ws.sent.append(data)
        if data["type"] == "init":
            profile["confidence"] = 0.9
        if data["type"] == "league_update":
            raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.POLL_INTERVAL_S", 0.001)
    monkeypatch.setattr("keisei.server.app.LEAGUE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_and_push(ws, asyncio.Lock(), db), timeout=1)
    assert ws.sent[-1]["style_profiles"][0]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_deleted_training_state_is_pushed_as_an_explicit_reset(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.db import write_training_state
    from keisei.server.app import _poll_and_push

    write_training_state(
        db,
        {
            "config_json": "{}",
            "display_name": "test",
            "model_arch": "resnet",
            "algorithm_name": "ppo",
            "started_at": "2026-01-01T00:00:00Z",
            "status": "idle",
            "current_epoch": 0,
            "current_step": 0,
            "learner_entry_id": 1,
        },
    )
    ws = Socket()

    async def send(data: dict) -> None:
        ws.sent.append(data)
        if data["type"] == "init":
            with _connect(db) as conn:
                conn.execute("DELETE FROM training_state")
        if data["type"] == "training_status":
            raise WebSocketDisconnect()

    ws.send_json = send
    monkeypatch.setattr("keisei.server.app.POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_and_push(ws, asyncio.Lock(), db), timeout=1)
    assert ws.sent[-1]["training_state"] is None


def test_auto_showcase_does_not_bypass_limit_after_stale_empty_queue_read(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from keisei.showcase.runner import ShowcaseRunner

    for _ in range(5):
        queue_match(db, "1", "2", "normal")
    # Another client can fill the queue after the runner's empty-queue read.
    monkeypatch.setattr("keisei.showcase.runner.read_queue", lambda _: [])
    runner = ShowcaseRunner(db, auto_showcase_interval=0)
    try:
        runner._maybe_auto_showcase()
    except ValueError:
        pass  # The competing client filled the queue first.
    assert len(read_queue(db)) == 5
