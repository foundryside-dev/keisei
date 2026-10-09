"""Read-only, epoch-complete gauntlet history pagination."""
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from keisei.db import init_db
from keisei.server.app import TEST_ALLOWED_HOSTS, create_app


@pytest.fixture
def history_db(tmp_path: Path) -> str:
    path = str(tmp_path / "history.db")
    init_db(path)
    return path


@pytest.mark.parametrize("epochs", [0, 6, 51])
def test_pages_complete_epochs_beyond_live_window(history_db: str, epochs: int) -> None:
    conn = sqlite3.connect(history_db)
    # Foreign keys intentionally disabled for isolated historical-result fixtures.
    conn.executemany(
        "INSERT INTO gauntlet_results (epoch,entry_id,historical_slot,historical_entry_id,wins,losses,draws) "
        "VALUES (?,1,?,2,2,1,3)",
        [(epoch, slot) for epoch in range(epochs) for slot in range(3)],
    )
    conn.commit()
    conn.close()
    before = Path(history_db).read_bytes()
    client = TestClient(create_app(history_db, allowed_hosts=TEST_ALLOWED_HOSTS))
    cursor = None
    ids = []
    seen_epochs = []
    while True:
        params = {"limit": 5}
        if cursor is not None:
            params["before_epoch"] = cursor
        response = client.get("/api/league/gauntlet", params=params)
        assert response.status_code == 200
        page = response.json()
        distinct = list(dict.fromkeys(row["epoch"] for row in page["results"]))
        assert len(distinct) <= 5
        assert len(page["results"]) == len(distinct) * 3
        assert distinct == sorted(distinct, reverse=True)
        seen_epochs.extend(distinct)
        ids.extend(row["id"] for row in page["results"])
        assert page["next_before_epoch"] == (distinct[-1] if distinct else None)
        if not page["has_more"]:
            break
        assert page["next_before_epoch"] != cursor
        cursor = page["next_before_epoch"]
    assert seen_epochs == list(reversed(range(epochs)))
    assert len(ids) == len(set(ids)) == epochs * 3
    assert Path(history_db).read_bytes() == before


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "limit=abc", "before_epoch=-1", "before_epoch=bad",
                                   "before_epoch=999999999999999999999"])
def test_invalid_history_cursor_and_limit(history_db: str, query: str) -> None:
    client = TestClient(create_app(history_db, allowed_hosts=TEST_ALLOWED_HOSTS))
    assert client.get(f"/api/league/gauntlet?{query}").status_code == 422
