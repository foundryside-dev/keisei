"""FastAPI spectator dashboard server."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from keisei.db import (
    init_db,
    read_elo_history,
    read_game_snapshots,
    read_game_snapshots_since,
    read_head_to_head,
    read_league_data,
    read_metrics_since,
    read_style_profiles,
    read_tournament_stats,
    read_training_state,
)
from keisei.db.showcase import (
    cancel_match as showcase_cancel_match,
)
from keisei.db.showcase import (
    queue_match as showcase_queue_match,
)
from keisei.db.showcase import (
    read_all_showcase_moves,
    read_latest_showcase_game,
    read_showcase_game,
    read_showcase_moves_since,
)
from keisei.db.showcase import (
    read_heartbeat as showcase_read_heartbeat,
)
from keisei.db.showcase import (
    read_queue as showcase_read_queue,
)
from keisei.db.showcase import (
    update_queue_speed as showcase_update_speed,
)

logger = logging.getLogger(__name__)


MAX_METRICS_IN_INIT = 500
POLL_INTERVAL_S = 0.2
ALLOWED_HOSTS = frozenset({"keisei.foundryside.dev", "192.168.1.240", "127.0.0.1", "localhost"})
# Superset for use in tests — includes synthetic hostnames from test clients
TEST_ALLOWED_HOSTS = ALLOWED_HOSTS | {"testserver", "test"}
SHOWCASE_POLL_INTERVAL_S = 0.5
VALID_SPEEDS = frozenset({"slow", "normal", "fast"})
MAX_SHOWCASE_QUEUE_DEPTH = 5
LEAGUE_POLL_INTERVAL_S = 5.0
POLL_BATCH_SIZE = 100
HEARTBEAT_STALE_S = 30
WS_SEND_TIMEOUT_S = 5.0
WS_PING_INTERVAL_S = 15.0


def _flatten_exception_group(eg: BaseException) -> "list[BaseException]":
    """Recursively flatten nested ExceptionGroups so logging never drops a leaf."""
    if isinstance(eg, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in eg.exceptions:
            leaves.extend(_flatten_exception_group(sub))
        return leaves
    return [eg]


async def _send_json(
    ws: WebSocket,
    send_lock: asyncio.Lock,
    msg: dict[str, Any],
    *,
    timeout: float = WS_SEND_TIMEOUT_S,
) -> None:
    """Send a JSON frame with a per-connection write lock.

    The legacy websockets protocol asserts in `_drain_helper` that no other
    coroutine is already draining (`assert waiter is None or waiter.cancelled()`
    at websockets/legacy/protocol.py:308). Our four background tasks all push
    independently, so without serialisation the second concurrent send blows
    up with a bare `AssertionError` and the connection dies. The lock makes
    sends single-writer per connection, which is the contract the library
    assumes.
    """
    async with send_lock:
        await asyncio.wait_for(ws.send_json(msg), timeout=timeout)


def _db_accessible(db_path: str) -> bool:
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            conn.execute("SELECT 1 FROM schema_version")
            return True
        finally:
            conn.close()
    except Exception:
        return False


def _get_system_stats() -> dict[str, Any]:
    """Get CPU and GPU utilization stats."""
    stats: dict[str, Any] = {}
    try:
        import psutil
        stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        stats["ram_used_gb"] = round(mem.used / (1024**3), 1)
        stats["ram_total_gb"] = round(mem.total / (1024**3), 1)
    except ImportError:
        stats["cpu_percent"] = None
        stats["ram_used_gb"] = None
        stats["ram_total_gb"] = None

    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            gpus: list[dict[str, int]] = []
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 3:
                    gpus.append({
                        "util_percent": int(parts[0]),
                        "mem_used_mb": int(parts[1]),
                        "mem_total_mb": int(parts[2]),
                    })
            stats["gpus"] = gpus
    except Exception:
        stats["gpus"] = []

    return stats


def _training_alive(db_path: str) -> bool:
    try:
        state = read_training_state(db_path)
        if state is None:
            return False
        hb = state.get("heartbeat_at", "")
        if not hb:
            return False
        hb_time = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - hb_time).total_seconds()
        return age < HEARTBEAT_STALE_S
    except Exception:
        return False


def _extract_hostname(host: str) -> str:
    """Extract hostname from a Host header, handling IPv6 bracketed literals.

    Examples: "localhost:8741" → "localhost", "[::1]:8741" → "::1", "" → ""
    """
    if host.startswith("["):
        # RFC 2732 bracketed IPv6: [::1]:port or [::1]
        bracket_end = host.find("]")
        if bracket_end != -1:
            return host[1:bracket_end]
        return host  # malformed — return as-is for rejection
    # IPv4 / hostname — strip port suffix
    return host.split(":")[0]


class HostFilterMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Host header isn't in the allowed set."""

    def __init__(self, app: Any, hosts: frozenset[str] = ALLOWED_HOSTS) -> None:
        super().__init__(app)
        self._hosts = hosts

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "")
        hostname = _extract_hostname(host)
        if hostname not in self._hosts:
            logger.warning("Rejected request with Host: %s", host)
            return PlainTextResponse("Forbidden", status_code=403)
        response: Response = await call_next(request)
        return response


def create_app(db_path: str, allowed_hosts: frozenset[str] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Server starting, db_path=%s", db_path)
        # Apply any pending schema migrations so dashboard queries
        # don't crash on columns added since the DB was created.
        await asyncio.to_thread(init_db, db_path)
        yield
        logger.info("Server shutting down")

    app = FastAPI(lifespan=lifespan)
    hosts = allowed_hosts if allowed_hosts is not None else ALLOWED_HOSTS
    app.add_middleware(HostFilterMiddleware, hosts=hosts)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        accessible = await asyncio.to_thread(_db_accessible, db_path)
        alive = await asyncio.to_thread(_training_alive, db_path) if accessible else False
        return JSONResponse({
            "status": "ok",
            "db_accessible": accessible,
            "training_alive": alive,
        })

    def _check_ws_host(websocket: WebSocket) -> bool:
        """Check websocket Host header against the allowlist.

        BaseHTTPMiddleware only filters HTTP scopes, not WebSocket scopes,
        so we enforce the same host allowlist here.
        """
        host = websocket.headers.get("host", "")
        hostname = _extract_hostname(host)
        return hostname in hosts

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        if not _check_ws_host(websocket):
            logger.warning("Rejected WebSocket with Host: %s", websocket.headers.get("host", ""))
            await websocket.close(code=1008, reason="Forbidden")
            return
        await websocket.accept()
        send_lock = asyncio.Lock()
        initialized: asyncio.Future[dict[str, Any] | None] = asyncio.get_running_loop().create_future()

        async def keepalive_after_init() -> None:
            await initialized
            await _keepalive(websocket, send_lock)

        async def commands_after_init() -> None:
            await initialized
            await _receive_commands(websocket, send_lock, db_path)

        async def showcase_after_init() -> None:
            game = await initialized
            await _poll_showcase(websocket, send_lock, db_path, initial_game=game)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(_poll_and_push(websocket, send_lock, db_path, initialized))
                tg.create_task(keepalive_after_init())
                tg.create_task(commands_after_init())
                tg.create_task(showcase_after_init())
        except* WebSocketDisconnect:
            pass
        except* asyncio.CancelledError:
            # Normal: client disconnected while a background DB thread was
            # in flight.  CancelledError is a BaseException and escapes
            # except* Exception, so it needs its own clause.
            pass
        except* Exception as eg:
            for exc in _flatten_exception_group(eg):
                if not isinstance(exc, WebSocketDisconnect):
                    # exc_info=exc surfaces the traceback for empty-message
                    # exceptions (TimeoutError, AssertionError) that would
                    # otherwise log as "WebSocket error: " with no context.
                    logger.warning("WebSocket error: %r", exc, exc_info=exc)

    # Mount audio assets from the repo root, kept out of the bundled static
    # directory because the file is ~700 MB. <audio> uses HTTP Range, so
    # StaticFiles streams it on demand. Must register before the catch-all "/".
    audio_dir = Path(__file__).resolve().parents[2] / "audio"
    if audio_dir.is_dir():
        app.mount("/audio", StaticFiles(directory=str(audio_dir)), name="audio")

    # Mount static files if the directory exists
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


async def _poll_and_push(
    ws: WebSocket, send_lock: asyncio.Lock, db_path: str,
    initialized: asyncio.Future[dict[str, Any] | None] | None = None,
) -> None:
    """Poll SQLite and push updates to the WebSocket client."""
    # Send init message
    metrics = await asyncio.to_thread(read_metrics_since, db_path, 0, MAX_METRICS_IN_INIT)
    games = await asyncio.to_thread(read_game_snapshots, db_path)
    state = await asyncio.to_thread(read_training_state, db_path)

    last_metrics_id = metrics[-1]["id"] if metrics else 0
    # Composite cursor for incremental game snapshot polling.
    # Tracks (timestamp, game_id) to avoid missing rows with equal timestamps.
    last_game_ts = ""
    last_game_id = 0
    if games:
        last_game_ts = max(g["updated_at"] for g in games)
        last_game_id = max(
            g["game_id"] for g in games if g["updated_at"] == last_game_ts
        )

    league_data = await asyncio.to_thread(read_league_data, db_path)
    # Match the steady-state cap below: an unbounded read at epoch 500+ produces
    # ~90k rows and pushes the init send past WS_SEND_TIMEOUT_S, killing the WS
    # before the client ever sees the payload. The frontend replaces eloHistory
    # on every league_update anyway, so it never holds more than this slice.
    elo_history = await asyncio.to_thread(read_elo_history, db_path, max_epochs=500)
    t_stats = await asyncio.to_thread(read_tournament_stats, db_path)
    style_profiles = await asyncio.to_thread(read_style_profiles, db_path)
    head_to_head = await asyncio.to_thread(read_head_to_head, db_path)

    # Showcase init data
    showcase_game = await asyncio.to_thread(read_latest_showcase_game, db_path)
    showcase_moves: list[dict[str, Any]] = []
    if showcase_game:
        showcase_moves = await asyncio.to_thread(read_all_showcase_moves, db_path, showcase_game["id"])
    showcase_queue = await asyncio.to_thread(showcase_read_queue, db_path)
    showcase_hb = await asyncio.to_thread(showcase_read_heartbeat, db_path)
    showcase_alive = False
    if showcase_hb:
        try:
            last_hb = datetime.fromisoformat(showcase_hb["last_heartbeat"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_hb).total_seconds()
            showcase_alive = age < HEARTBEAT_STALE_S
        except (ValueError, TypeError):
            pass

    await _send_json(ws, send_lock, {
        "type": "init",
        "games": games,
        "metrics": metrics,
        "training_state": state,
        "league_entries": league_data["entries"],
        "league_results": league_data["results"],
        "league_totals": league_data["totals"],
        "entry_records": league_data["entry_records"],
        "learner_recent_record": league_data["learner_recent_record"],
        "historical_library": league_data["historical_library"],
        "gauntlet_results": league_data["gauntlet_results"],
        "transitions": league_data["transitions"],
        "elo_history": elo_history,
        "tournament_stats": t_stats,
        "style_profiles": style_profiles,
        "head_to_head": head_to_head,
        "showcase": {
            "game": dict(showcase_game) if showcase_game else None,
            "moves": showcase_moves,
            "queue": showcase_queue,
            "sidecar_alive": showcase_alive,
        },
    })

    if initialized is not None and not initialized.done():
        initialized.set_result(showcase_game)

    last_league_payload = (league_data, elo_history, t_stats)
    league_poll_elapsed = 0.0
    total_episodes = sum((m.get("episodes_completed") or 0) for m in metrics)

    # Poll loop
    while True:
        await asyncio.sleep(POLL_INTERVAL_S)

        new_metrics = await asyncio.to_thread(
            read_metrics_since, db_path, last_metrics_id, POLL_BATCH_SIZE
        )
        if new_metrics:
            last_metrics_id = new_metrics[-1]["id"]
            total_episodes += sum(
                (m.get("episodes_completed") or 0) for m in new_metrics
            )
            await _send_json(ws, send_lock, {"type": "metrics_update", "rows": new_metrics})

        changed_games, new_game_ts, new_game_id = await asyncio.to_thread(
            read_game_snapshots_since, db_path, last_game_ts, last_game_id
        )
        if changed_games:
            last_game_ts = new_game_ts
            last_game_id = new_game_id
            await _send_json(ws, send_lock, {"type": "game_update", "snapshots": changed_games})

        new_state = await asyncio.to_thread(read_training_state, db_path)
        if new_state != state:
            sys_stats = await asyncio.to_thread(_get_system_stats)
            state = new_state
            status_state = new_state or {}
            await _send_json(ws, send_lock, {
                "type": "training_status",
                "training_state": new_state,
                "status": status_state.get("status"),
                "phase": status_state.get("phase", ""),
                "heartbeat_at": status_state.get("heartbeat_at"),
                "epoch": status_state.get("current_epoch"),
                "step": status_state.get("current_step"),
                "episodes": total_episodes,
                "config_json": status_state.get("config_json"),
                "display_name": status_state.get("display_name"),
                "model_arch": status_state.get("model_arch"),
                "total_epochs": status_state.get("total_epochs"),
                "system_stats": sys_stats,
                "learner_entry_id": status_state.get("learner_entry_id"),
            })

        league_poll_elapsed += POLL_INTERVAL_S
        if league_poll_elapsed >= LEAGUE_POLL_INTERVAL_S:
            league_poll_elapsed = 0.0
            new_league = await asyncio.to_thread(read_league_data, db_path)
            new_elo_hist = await asyncio.to_thread(read_elo_history, db_path, max_epochs=500)
            new_t_stats = await asyncio.to_thread(read_tournament_stats, db_path)
            new_league_payload = (new_league, new_elo_hist, new_t_stats)
            league_changed = new_league_payload != last_league_payload
            # Profiles can finish asynchronously after a tournament has published.
            new_style = await asyncio.to_thread(read_style_profiles, db_path)
            style_changed = new_style != style_profiles
            if league_changed:
                head_to_head = await asyncio.to_thread(read_head_to_head, db_path)
            if style_changed:
                style_profiles = new_style

            if league_changed or style_changed:
                last_league_payload = new_league_payload
                msg: dict[str, Any] = {
                    "type": "league_update",
                    "entries": new_league["entries"],
                    "results": new_league["results"],
                    "league_totals": new_league["totals"],
                    "entry_records": new_league["entry_records"],
                    "learner_recent_record": new_league["learner_recent_record"],
                    "historical_library": new_league["historical_library"],
                    "gauntlet_results": new_league["gauntlet_results"],
                    "transitions": new_league["transitions"],
                    "elo_history": new_elo_hist,
                    "tournament_stats": new_t_stats,
                    "head_to_head": head_to_head,
                }
                if style_changed:
                    msg["style_profiles"] = style_profiles
                await _send_json(ws, send_lock, msg)


async def _keepalive(ws: WebSocket, send_lock: asyncio.Lock) -> None:
    """Ping/pong heartbeat to detect dead connections."""
    while True:
        await asyncio.sleep(WS_PING_INTERVAL_S)
        try:
            await _send_json(ws, send_lock, {"type": "ping"})
        except (WebSocketDisconnect, ConnectionError, asyncio.TimeoutError):
            raise WebSocketDisconnect()


async def _command_reply(
    ws: WebSocket, send_lock: asyncio.Lock, data: dict[str, Any], message: dict[str, Any],
) -> None:
    request_id = data.get("request_id")
    if isinstance(request_id, str):
        message["request_id"] = request_id
    await _send_json(ws, send_lock, message)


def _positive_id(value: Any) -> int | None:
    # Reject bool/float instead of silently coercing a different queue/entry ID.
    if type(value) is int:
        return value if 0 < value <= 2**63 - 1 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
        return parsed if 0 < parsed <= 2**63 - 1 else None
    return None


async def _receive_commands(ws: WebSocket, send_lock: asyncio.Lock, db_path: str) -> None:
    """Reject malformed commands while keeping the connection usable."""
    while True:
        try:
            raw = await ws.receive_text()
        except asyncio.CancelledError:
            raise WebSocketDisconnect() from None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            await _send_json(ws, send_lock, {"type": "showcase_error", "error": "Command must be a JSON object"})
            continue
        if not isinstance(data, dict):
            await _send_json(ws, send_lock, {"type": "showcase_error", "error": "Command must be a JSON object"})
            continue
        msg_type = data.get("type", "")
        try:
            if msg_type == "request_showcase_match":
                await _handle_match_request(ws, send_lock, db_path, data)
            elif msg_type == "change_showcase_speed":
                await _handle_speed_change(ws, send_lock, db_path, data)
            elif msg_type == "cancel_showcase_match":
                await _handle_cancel(ws, send_lock, db_path, data)
            elif msg_type != "pong":
                await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": "Unknown command"})
        except (WebSocketDisconnect, ConnectionError):
            raise
        except Exception:
            logger.exception("Error handling client command %s", msg_type)
            await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": "Command failed; please try again"})


async def _handle_match_request(ws: WebSocket, send_lock: asyncio.Lock, db_path: str, data: dict[str, Any]) -> None:
    entry_id_1 = _positive_id(data.get("entry_id_1"))
    entry_id_2 = _positive_id(data.get("entry_id_2"))
    speed = data.get("speed", "normal")
    error = None
    if not isinstance(speed, str) or speed not in VALID_SPEEDS:
        error = "Invalid speed"
    elif entry_id_1 is None or entry_id_2 is None:
        error = "Both entry_id_1 and entry_id_2 must be positive integer IDs"
    elif entry_id_1 == entry_id_2:
        error = "Cannot match an entry against itself"
    if error:
        await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": error})
        return
    try:
        queue_id = await asyncio.to_thread(
            showcase_queue_match, db_path, str(entry_id_1), str(entry_id_2), speed,
            max_pending=MAX_SHOWCASE_QUEUE_DEPTH, validate_entries=True,
        )
    except ValueError as exc:
        await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": str(exc)})
        return
    await _command_reply(ws, send_lock, data, {
        "type": "showcase_match_queued", "queue_id": queue_id,
        "entry_id_1": str(entry_id_1), "entry_id_2": str(entry_id_2), "speed": speed,
    })


async def _handle_speed_change(ws: WebSocket, send_lock: asyncio.Lock, db_path: str, data: dict[str, Any]) -> None:
    queue_id = _positive_id(data.get("queue_id"))
    speed = data.get("speed", "")
    error = None
    if not isinstance(speed, str) or speed not in VALID_SPEEDS:
        error = "Invalid speed"
    elif queue_id is None:
        error = "queue_id must be a positive integer"
    elif not await asyncio.to_thread(showcase_update_speed, db_path, queue_id, speed):
        error = "Match is no longer queued or running"
    if error:
        await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": error})
        return
    await _command_reply(ws, send_lock, data, {"type": "showcase_speed_changed", "queue_id": queue_id, "speed": speed})


async def _handle_cancel(ws: WebSocket, send_lock: asyncio.Lock, db_path: str, data: dict[str, Any]) -> None:
    queue_id = _positive_id(data.get("queue_id"))
    error = None
    if queue_id is None:
        error = "queue_id must be a positive integer"
    elif not await asyncio.to_thread(showcase_cancel_match, db_path, queue_id):
        error = "Only pending matches can be cancelled"
    if error:
        await _command_reply(ws, send_lock, data, {"type": "showcase_error", "error": error})
        return
    await _command_reply(ws, send_lock, data, {"type": "showcase_match_cancelled", "queue_id": queue_id})


async def _poll_showcase(
    ws: WebSocket, send_lock: asyncio.Lock, db_path: str,
    *, initial_game: dict[str, Any] | None = None,
) -> None:
    """Poll showcase tables and push incremental updates.

    Uses incremental move delivery: only moves since last_sent_ply are sent.
    Status updates use fingerprinting to avoid redundant sends.
    """
    last_status_fingerprint: tuple[Any, ...] | None = None
    last_game = initial_game
    last_game_id = initial_game["id"] if initial_game else None
    last_sent_ply = initial_game["total_ply"] if initial_game else 0

    while True:
        await asyncio.sleep(SHOWCASE_POLL_INTERVAL_S)

        game = await asyncio.to_thread(read_latest_showcase_game, db_path)
        queue = await asyncio.to_thread(showcase_read_queue, db_path)
        hb = await asyncio.to_thread(showcase_read_heartbeat, db_path)

        alive = False
        if hb:
            try:
                last_hb = datetime.fromisoformat(hb["last_heartbeat"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - last_hb).total_seconds()
                alive = age < HEARTBEAT_STALE_S
            except (ValueError, TypeError):
                pass

        game_id = game["id"] if game else None

        # A queued successor may start before this poll. Finish the previous
        # game's stream before resetting its move cursor.
        if game_id != last_game_id:
            if last_game_id is not None:
                previous = await asyncio.to_thread(read_showcase_game, db_path, last_game_id)
                final_moves = await asyncio.to_thread(read_showcase_moves_since, db_path, last_game_id, last_sent_ply)
                if previous and (previous != last_game or final_moves):
                    await _send_json(ws, send_lock, {
                        "type": "showcase_update", "game": previous, "new_moves": final_moves,
                    })
            last_sent_ply = 0
            last_game_id = game_id

        # Deliver final metadata/moves before announcing the game is idle.
        if game:
            new_moves = await asyncio.to_thread(
                read_showcase_moves_since, db_path, game["id"], last_sent_ply,
            )
            if new_moves or game != last_game:
                last_game = dict(game)
                if new_moves:
                    last_sent_ply = max(m["ply"] for m in new_moves)
                await _send_json(ws, send_lock, {
                    "type": "showcase_update", "game": dict(game), "new_moves": new_moves,
                })

        active_game_id = game_id if game and game["status"] == "in_progress" else None
        status_fingerprint = (active_game_id, json.dumps(queue, sort_keys=True), alive)
        if status_fingerprint != last_status_fingerprint:
            last_status_fingerprint = status_fingerprint
            await _send_json(ws, send_lock, {
                "type": "showcase_status", "queue": queue,
                "active_game_id": active_game_id, "sidecar_alive": alive,
            })


def create_app_from_env() -> FastAPI:
    """Factory for uvicorn --factory mode. Reads KEISEI_CONFIG env var."""
    import os

    from keisei.config import load_config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config_path = os.environ.get("KEISEI_CONFIG", "keisei-league.toml")
    config = load_config(Path(config_path))
    return create_app(config.display.db_path)


def main() -> None:
    """CLI entry point: keisei-serve."""
    import argparse

    import uvicorn

    from keisei.config import load_config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Keisei spectator dashboard")
    parser.add_argument("--config", type=Path, required=True, help="Path to TOML config")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (ignored if --socket)")
    parser.add_argument("--port", type=int, default=8741, help="Bind port (ignored if --socket)")
    parser.add_argument("--socket", default=None, help="Unix domain socket path (overrides --host/--port)")
    args = parser.parse_args()

    config = load_config(args.config)
    app = create_app(config.display.db_path)
    if args.socket:
        uvicorn.run(app, uds=args.socket)
    else:
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
