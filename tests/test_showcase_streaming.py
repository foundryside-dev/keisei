"""Showcase streaming preserves results across game and connection boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from keisei.db import init_db
from keisei.db.showcase import (
    claim_next_match,
    complete_queue_entry,
    create_showcase_game,
    mark_game_completed,
    queue_match,
    write_showcase_move,
)
from keisei.server.app import _poll_showcase, _send_json, create_app


@pytest.mark.asyncio
async def test_back_to_back_games_deliver_previous_terminal_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = str(tmp_path / "streaming.db")
    init_db(db)
    first_queue = queue_match(db, "1", "2", "fast")
    second_queue = queue_match(db, "1", "2", "fast")
    assert claim_next_match(db) is not None

    def create_game(queue_id: int) -> int:
        return create_showcase_game(
            db, queue_id=queue_id, entry_id_black="1", entry_id_white="2",
            elo_black=1500, elo_white=1500, name_black="A", name_white="B",
        )

    first_game = create_game(first_queue)
    sent: list[dict[str, Any]] = []
    advanced = False

    class Socket:
        async def send_json(self, message: dict[str, Any]) -> None:
            nonlocal advanced
            sent.append(message)
            if message["type"] != "showcase_update":
                return
            if message["game"]["id"] != first_game:
                raise WebSocketDisconnect()
            if advanced:
                return
            advanced = True
            # The runner can finish and start another queued game before the
            # next poll. The final move must be read using the old game ID.
            write_showcase_move(
                db, game_id=first_game, ply=1, action_index=0,
                usi_notation="7g7f", board_json="[]", hands_json="{}",
                current_player="white", in_check=False, value_estimate=0.5,
                top_candidates="[]", move_time_ms=1,
            )
            mark_game_completed(db, first_game, "black_win", 1)
            complete_queue_entry(db, first_queue)
            assert claim_next_match(db)["id"] == second_queue
            create_game(second_queue)

    monkeypatch.setattr("keisei.server.app.SHOWCASE_POLL_INTERVAL_S", 0.001)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(_poll_showcase(Socket(), asyncio.Lock(), db), timeout=2)

    updates = [m for m in sent if m["type"] == "showcase_update"]
    terminal = [m for m in updates if m["game"]["id"] == first_game and m["game"]["status"] == "black_win"]
    assert len(terminal) == 1
    assert [move["ply"] for move in terminal[0]["new_moves"]] == [1]
    assert updates.index(terminal[0]) < len(updates) - 1


@pytest.mark.asyncio
async def test_websocket_initialization_precedes_showcase_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = str(tmp_path / "initialization.db")
    init_db(db)
    queue_id = queue_match(db, "1", "2", "normal")
    create_showcase_game(
        db, queue_id=queue_id, entry_id_black="1", entry_id_white="2",
        elo_black=1500, elo_white=1500, name_black="A", name_white="B",
    )
    sent: list[dict[str, Any]] = []

    class Socket:
        headers = {"host": "localhost"}

        async def accept(self) -> None:
            pass

        async def receive_text(self) -> str:
            await asyncio.Future()
            raise AssertionError("unreachable")

        async def send_json(self, message: dict[str, Any]) -> None:
            sent.append(message)
            # One frame is enough to establish which task won the race.
            raise WebSocketDisconnect()

    async def slow_initialization(ws: Any, lock: asyncio.Lock, *args: Any, **kwargs: Any) -> None:
        # Loading the training/league snapshot can take longer than one
        # showcase poll. The endpoint must still send init first.
        await asyncio.sleep(0.05)
        await _send_json(ws, lock, {"type": "init"})

    monkeypatch.setattr("keisei.server.app._poll_and_push", slow_initialization)
    monkeypatch.setattr("keisei.server.app.SHOWCASE_POLL_INTERVAL_S", 0.001)
    app = create_app(db)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ws")
    await asyncio.wait_for(endpoint(Socket()), timeout=2)
    assert sent[0]["type"] == "init"
