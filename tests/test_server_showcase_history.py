"""Saved-match deep links read persisted games without loading models."""
import json
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from keisei.db import init_db
from keisei.db.showcase import create_showcase_game, queue_match, write_showcase_move
from keisei.server.app import TEST_ALLOWED_HOSTS, create_app


@pytest.fixture
def saved_db(tmp_path: Path) -> tuple[str, int]:
    path = str(tmp_path / "saved.db")
    init_db(path)
    qid = queue_match(path, "a", "b", "normal")
    gid = create_showcase_game(path, queue_id=qid, entry_id_black="a", entry_id_white="b",
                               elo_black=1500, elo_white=1500, name_black="A", name_white="B")
    return path, gid


def test_saved_match_order_and_evaluation_contract(saved_db: tuple[str, int]) -> None:
    path, gid = saved_db
    evaluation = {"version": 1, "kind": "outcome_score", "score": 0.55, "player": "white",
                  "position_ply": 1, "source": {"architecture": "se_resnet", "contract": "multi_head"},
                  "wdl": {"win": 0.2, "draw": 0.7, "loss": 0.1}}
    for ply in [2, 1]:
        write_showcase_move(path, game_id=gid, ply=ply, action_index=1, usi_notation="P-7f",
                            board_json="[]", hands_json="{}", current_player="black",
                            in_check=False, value_estimate=0.2, top_candidates="[]", move_time_ms=1,
                            evaluation_json=json.dumps(evaluation) if ply == 2 else None)
    before = Path(path).read_bytes()
    client = TestClient(create_app(path, allowed_hosts=TEST_ALLOWED_HOSTS))
    response = client.get(f"/api/showcase/games/{gid}")
    assert response.status_code == 200
    saved = response.json()
    assert saved["game"]["id"] == gid
    assert [move["ply"] for move in saved["moves"]] == [1, 2]
    assert saved["moves"][0]["evaluation_json"] is None
    assert json.loads(saved["moves"][1]["evaluation_json"]) == evaluation
    assert saved["moves"][1]["value_estimate"] == 0.2
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("game_id,code", [(999, 404), (0, 422), (-1, 422), ("abc", 422),
                                        (999999999999999999999, 422)])
def test_saved_match_absent_and_invalid_ids(saved_db: tuple[str, int], game_id: str | int, code: int) -> None:
    path, _ = saved_db
    client = TestClient(create_app(path, allowed_hosts=TEST_ALLOWED_HOSTS))
    assert client.get(f"/api/showcase/games/{game_id}").status_code == code


@pytest.mark.parametrize("count,code", [(2048, 200), (2049, 413)])
def test_saved_match_move_ceiling(saved_db: tuple[str, int], count: int, code: int) -> None:
    path, gid = saved_db
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO showcase_moves (game_id,ply,action_index,usi_notation,board_json,hands_json,current_player,created_at) "
        "VALUES (?,?,1,'P-7f','[]','{}','white','2026-01-01')", [(gid, ply) for ply in range(1, count + 1)],
    )
    conn.commit()
    conn.close()
    client = TestClient(create_app(path, allowed_hosts=TEST_ALLOWED_HOSTS))
    response = client.get(f"/api/showcase/games/{gid}")
    assert response.status_code == code
    if code == 413:
        assert "2048-move" in response.json()["detail"]
    else:
        assert len(response.json()["moves"]) == count
