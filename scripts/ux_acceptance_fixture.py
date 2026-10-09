"""Disposable UX acceptance fixture using real SQLite, create_app, WebSocket and API.

Serve: .venv/bin/python -m scripts.ux_acceptance_fixture --port 8765
Mutate: .venv/bin/python -m scripts.ux_acceptance_fixture --db DB --action append-move
Use --seed-only to create data without serving. Use --action new-match to complete
the current live match and create another while preserving archived IDs.
Never opens the configured training DB. Every seed uses a fresh tempfile directory.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

# Support direct script execution as well as python -m, resolving this checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ruff: noqa: E402
from shogi_gym import SpectatorEnv

from keisei.db import init_db, write_game_snapshots, write_metrics, write_training_state
from keisei.db.showcase import create_showcase_game, mark_game_completed, queue_match, write_heartbeat, write_showcase_move
from keisei.db.training_state import update_heartbeat
from keisei.server.app import create_app
from keisei.showcase.heatmap import build_heatmap

START_SFEN = "4k4/9/3+p5/9/4+B4/9/9/9/4K4 b R2Pgs 1"


def serial_move(db, game_id, state, previous, usi, action, legacy=False, malformed=False):
    ply = state["ply"]
    evaluation = {
        "version": 1,
        "kind": "outcome_score",
        "score": 0.55 if ply % 2 else 0.8,
        "player": previous["current_player"],
        "position_ply": ply - 1,
        "source": {"architecture": "resnet", "contract": "scalar"},
    }
    if malformed:
        evaluation["score"] = 2
    pre_move_env = SpectatorEnv.from_sfen(previous["sfen"], max_ply=120)
    legal = pre_move_env.legal_moves_with_usi()
    weights = {index: (12.0 if index == action else 1.0) for index, _ in legal}
    total = sum(weights.values())
    probabilities = {index: weight / total for index, weight in weights.items()}
    heatmap = build_heatmap(chosen_usi=usi, legal_with_usi=legal, probs=probabilities)
    write_showcase_move(
        db,
        game_id=game_id,
        ply=ply,
        action_index=action,
        usi_notation=state["move_history"][-1]["notation"] if state["move_history"] else "Initial position",
        board_json=json.dumps(state["board"]),
        hands_json=json.dumps(state["hands"]),
        current_player=state["current_player"],
        in_check=state["in_check"],
        value_estimate=0.55,
        evaluation_json=None if legacy else json.dumps(evaluation),
        top_candidates=json.dumps(
            [
                {
                    "action": action,
                    "usi": state["move_history"][-1]["notation"] if state["move_history"] else usi,
                    "probability": probabilities[action],
                }
            ]
        ),
        move_time_ms=124,
        move_heatmap_json=json.dumps(heatmap),
        move_usi=usi,
    )


def replay_states():
    env = SpectatorEnv.from_sfen(START_SFEN, max_ply=120)
    states = [env.to_dict()]
    actions = []
    for i in range(30):
        if env.is_over:
            break
        moves = sorted(env.legal_moves_with_usi(), key=lambda pair: pair[1])
        # Prefer a real drop to exercise held-piece/last-move handling, then keep
        # a deterministic legal sequence. The initial SFEN has promoted pieces.
        drops = [pair for pair in moves if "*" in pair[1]]
        action, usi = drops[(i * 7) % len(drops)] if drops and i < 4 else moves[(i * 13 + 3) % len(moves)]
        actions.append((action, usi))
        states.append(env.step(action))
    return states, actions


def seed():
    directory = Path(tempfile.mkdtemp(prefix="keisei-ux08-"))
    db = str(directory / "fixture.sqlite")
    init_db(db)
    with sqlite3.connect(db) as conn:
        for entry_id in range(1, 22):
            name = (
                "Ivory Crane — Long Snapshot Name for Investigation"
                if entry_id in (1, 2)
                else f"Vermilion Strategist {entry_id:02d} — Long Snapshot Name"
            )
            role = ["frontier_static", "recent_fixed", "dynamic", "historical"][(entry_id - 1) % 4]
            conn.execute(
                "INSERT INTO league_entries (id,display_name,architecture,model_params,checkpoint_path,"
                "elo_rating,created_epoch,games_played,role,status,flavour_facts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry_id,
                    name,
                    "resnet",
                    json.dumps({"channels": 128, "num_blocks": 8}),
                    "/tmp/fixture-only-no-model.pt",
                    1600 - entry_id * 17,
                    entry_id * 13,
                    entry_id * 42,
                    role,
                    "retired" if entry_id == 21 else "active",
                    json.dumps([["Preference", "Enjoys long endgames"], ["Study", "Promoted-piece attacks"]]),
                ),
            )
            for epoch in range(1, 52):
                conn.execute(
                    "INSERT INTO elo_history(entry_id,epoch,elo_rating) VALUES(?,?,?)", (entry_id, epoch, 1000 + epoch * 5 + entry_id * 3)
                )
        for slot in range(5):
            conn.execute(
                "INSERT INTO historical_library(slot_index,target_epoch,entry_id,actual_epoch,selected_at,"
                "selection_mode) VALUES(?,?,?,?,?,?)",
                (slot, 10 * slot, slot + 15, 10 * slot, "2026-10-10T00:00:00Z", "nearest"),
            )
        for epoch in range(1, 52):
            for slot in range(5):
                conn.execute(
                    "INSERT INTO gauntlet_results(epoch,entry_id,historical_slot,historical_entry_id,wins,"
                    "losses,draws,elo_before,elo_after) VALUES(?,?,?,?,?,?,?,?,?)",
                    (epoch, 1, slot, 15 + slot, 7 + slot, 2, 1, 1200 + epoch, 1204 + epoch),
                )
        for a in range(1, 20):
            b = a + 1
            conn.execute(
                "INSERT INTO league_results(epoch,entry_a_id,entry_b_id,match_type,num_games,wins_a,wins_b,"
                "draws,elo_before_a,elo_after_a,elo_before_b,elo_after_b) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (51, a, b, "fixture", 12, 7, 3, 2, 1300, 1304, 1200, 1196),
            )
            conn.execute(
                "INSERT INTO head_to_head(entry_a_id,entry_b_id,wins_a,wins_b,draws,games,last_epoch) VALUES(?,?,?,?,?,?,?)",
                (a, b, 7, 3, 2, 12, 51),
            )
        conn.execute(
            "INSERT INTO tournament_stats(id,round_duration_s,pairings_requested,pairings_completed,"
            "total_games,total_plies,active_slots,games_per_min) VALUES(1,20,19,19,228,6000,32,684)"
        )
    write_training_state(
        db,
        {
            "config_json": json.dumps(
                {
                    "training": {"num_envs": 32, "total_epochs": 1000},
                    "league": {
                        "max_active_entries": 20,
                        "frontier": {"slots": 5},
                        "recent": {"slots": 5},
                        "dynamic": {"slots": 10},
                        "history": {"slots": 5},
                    },
                }
            ),
            "display_name": "Ivory Crane — Long Snapshot Name for Investigation",
            "model_arch": "resnet",
            "algorithm_name": "ppo",
            "started_at": "2026-10-10T00:00:00Z",
            "current_epoch": 51,
            "current_step": 104448,
            "total_epochs": 1000,
            "phase": "rollout",
            "learner_entry_id": 1,
        },
    )
    for epoch in range(1, 52):
        write_metrics(
            db,
            {
                "epoch": epoch,
                "step": epoch * 2048,
                "policy_loss": 0.8 / math.sqrt(epoch),
                "value_loss": 0.5 / math.sqrt(epoch),
                "entropy": 3.5 - epoch * 0.03,
                "win_rate": 0.5 + epoch * 0.003,
                "loss_rate": 0.4 - epoch * 0.002,
                "draw_rate": 0.1,
                "black_win_rate": 0.53,
                "white_win_rate": 0.51,
                "truncation_rate": 0.02,
                "avg_episode_length": 120 + epoch,
                "gradient_norm": 0.8,
                "episodes_completed": 32,
            },
        )
    states, actions = replay_states()
    snapshots = []
    for lane in range(32):
        state = states[min(lane % 12 + 1, len(states) - 1)]
        snapshots.append(
            {
                "game_id": lane,
                "board_json": json.dumps(state["board"]),
                "hands_json": json.dumps(state["hands"]),
                "current_player": state["current_player"],
                "ply": state["ply"],
                "is_over": int(lane == 31),
                "result": "draw" if lane == 31 else "in_progress",
                "sfen": state["sfen"],
                "in_check": int(state["in_check"]),
                "move_history_json": json.dumps(state["move_history"]),
                "value_estimate": 0.25,
                "game_type": "live",
                "opponent_id": lane % 19 + 2,
            }
        )
    write_game_snapshots(db, snapshots)
    for game_id in (1, 2, 3):
        qid = queue_match(db, "1", "2", "normal")
        actual_id = create_showcase_game(
            db,
            queue_id=qid,
            entry_id_black="1",
            entry_id_white="2",
            elo_black=1583,
            elo_white=1566,
            name_black="Ivory Crane — Long Snapshot Name for Investigation",
            name_white="Ivory Crane — Long Snapshot Name for Investigation",
        )
        assert actual_id == game_id
        for index in range(12):
            action, usi = actions[index]
            serial_move(
                db, game_id, states[index + 1], states[index], usi, action, legacy=(game_id == 2), malformed=(game_id == 1 and index == 4)
            )
        if game_id < 3:
            mark_game_completed(db, game_id, "draw", 12)
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE showcase_queue SET status=? WHERE id=?", ("running" if game_id == 3 else "completed", qid))
    write_heartbeat(db, os.getpid())
    metadata = {
        "db": db,
        "directory": str(directory),
        "lanes": 32,
        "active_entries": 20,
        "duplicate_entry_ids": [1, 2],
        "retired_entry_id": 21,
        "evaluation_epochs": 51,
        "evaluation_slots": 5,
        "saved_game_id": 1,
        "legacy_game_id": 2,
        "live_game_id": 3,
        "initial_live_ply": 12,
        "states": states,
        "actions": actions,
    }
    (directory / "metadata.json").write_text(json.dumps(metadata))
    return metadata


def load_fixture_metadata(db):
    path = Path(db).resolve()
    if path.name != "fixture.sqlite" or not path.parent.name.startswith("keisei-ux08-"):
        raise ValueError("Operation requires an explicitly disposable keisei-ux08 fixture DB")
    metadata = json.loads((path.parent / "metadata.json").read_text())
    if Path(metadata["db"]).resolve() != path:
        raise ValueError("Fixture metadata does not identify the requested DB")
    return metadata


def mutate(db, action):
    directory = Path(db).parent
    metadata = load_fixture_metadata(db)
    with sqlite3.connect(db) as conn:
        if action == "complete-lane":
            conn.execute(
                "UPDATE game_snapshots SET is_over=1,result='draw',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE game_id=0"
            )
        elif action == "replace-lane":
            initial = metadata["states"][0]
            conn.execute(
                "UPDATE game_snapshots SET is_over=0,result='in_progress',ply=0,move_history_json='[]',"
                "board_json=?,hands_json=?,current_player=?,sfen=?,in_check=?,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE game_id=0",
                (
                    json.dumps(initial["board"]),
                    json.dumps(initial["hands"]),
                    initial["current_player"],
                    initial["sfen"],
                    int(initial["in_check"]),
                ),
            )
        elif action == "remove-lane":
            conn.execute("DELETE FROM game_snapshots WHERE game_id=0")
        elif action == "zero-lanes":
            conn.execute("DELETE FROM game_snapshots")
        elif action == "new-evaluation":
            epoch = conn.execute("SELECT max(epoch)+1 FROM gauntlet_results").fetchone()[0]
            for slot in range(5):
                conn.execute(
                    "INSERT INTO gauntlet_results(epoch,entry_id,historical_slot,historical_entry_id,wins,"
                    "losses,draws,elo_before,elo_after) VALUES(?,?,?,?,?,?,?,?,?)",
                    (epoch, 1, slot, slot + 15, 8, 1, 1, 1300, 1304),
                )
        elif action == "remove-entry":
            conn.execute("UPDATE league_entries SET status='retired' WHERE id=1")
        elif action == "sidecar-off":
            (directory / "sidecar-off").touch()
            conn.execute("UPDATE showcase_heartbeat SET last_heartbeat='2000-01-01T00:00:00Z'")
        elif action == "sidecar-on":
            (directory / "sidecar-off").unlink(missing_ok=True)
        elif action == "append-move":
            game_id = metadata["live_game_id"]
            ply = conn.execute("SELECT max(ply) FROM showcase_moves WHERE game_id=?", (game_id,)).fetchone()[0]
            state = metadata["states"][ply + 1]
            previous = metadata["states"][ply]
            index, usi = metadata["actions"][ply]
            conn.commit()
            serial_move(db, game_id, state, previous, usi, index)
        elif action == "new-match":
            previous_id = metadata["live_game_id"]
            conn.execute(
                "UPDATE showcase_games SET status='draw', completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (previous_id,)
            )
            conn.execute("UPDATE showcase_queue SET status='completed' WHERE status='running'")
            conn.commit()
            queue_id = queue_match(db, "1", "2", "normal")
            game_id = create_showcase_game(
                db,
                queue_id=queue_id,
                entry_id_black="1",
                entry_id_white="2",
                elo_black=1583,
                elo_white=1566,
                name_black="Ivory Crane — Long Snapshot Name for Investigation",
                name_white="Ivory Crane — Long Snapshot Name for Investigation",
            )
            for index in range(12):
                move_action, usi = metadata["actions"][index]
                serial_move(db, game_id, metadata["states"][index + 1], metadata["states"][index], usi, move_action)
            conn.execute("UPDATE showcase_queue SET status='running' WHERE id=?", (queue_id,))
            metadata["previous_live_game_id"] = previous_id
            metadata["live_game_id"] = game_id
            (directory / "metadata.json").write_text(json.dumps(metadata))
        else:
            raise ValueError(action)
    print(json.dumps({"mutated": action, "db": db, "live_game_id": metadata["live_game_id"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db")
    parser.add_argument("--action")
    parser.add_argument("--seed-only", action="store_true", help="Create and print fixture metadata without starting a server")
    args = parser.parse_args()
    if args.action:
        if not args.db or not Path(args.db).parent.name.startswith("keisei-ux08-"):
            raise ValueError("Mutation requires an explicitly disposable keisei-ux08 DB")
        mutate(args.db, args.action)
        return
    if args.db:
        if not Path(args.db).parent.name.startswith("keisei-ux08-"):
            raise ValueError("Existing serve requires a disposable keisei-ux08 DB")
        metadata = load_fixture_metadata(args.db)
    else:
        metadata = seed()
    db = metadata["db"]
    if args.seed_only:
        print(json.dumps({key: value for key, value in metadata.items() if key not in ("states", "actions")}, indent=2))
        return

    def heartbeats():
        while True:
            update_heartbeat(db)
            if not (Path(db).parent / "sidecar-off").exists():
                write_heartbeat(db, os.getpid())
            time.sleep(5)

    threading.Thread(target=heartbeats, daemon=True).start()
    print(json.dumps({key: value for key, value in metadata.items() if key not in ("states", "actions")}, indent=2), flush=True)
    # The production poller supplies real host CPU/GPU statistics on heartbeat
    # updates. They are acceptance context, not deterministic fixture values.
    import uvicorn

    uvicorn.run(create_app(db), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
