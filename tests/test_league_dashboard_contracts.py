"""Dashboard history windows must not redefine cumulative league records."""

import sqlite3

import keisei.db.league as league_module
from keisei.db import init_db, read_league_data


def test_lifetime_records_survive_recent_feed_limit_and_retirement(tmp_path):
    path = str(tmp_path / "league.db")
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO league_entries (id,architecture,model_params,checkpoint_path,created_epoch,status) "
            "VALUES (?, 'resnet', '{}', '/fake.pt', 0, ?)",
            [(1, "retired"), (2, "active"), (3, "active")],
        )
        conn.executemany(
            "INSERT INTO league_results "
            "(epoch,entry_a_id,entry_b_id,match_type,num_games,wins_a,wins_b,draws) "
            "VALUES (?, ?, ?, 'calibration', ?, ?, ?, ?)",
            [(0, 2, 1, 6, 2, 3, 1)] + [(epoch, 2, 3, 1, 1, 0, 0) for epoch in range(1, 502)],
        )

    for limit in [500, 1, 0]:
        data = read_league_data(path, max_results=limit)
        assert len(data["results"]) == min(limit, 502)
        assert data["totals"] == {"matches": 502, "rounds": 502, "games": 507}
        records = {row["entry_id"]: row for row in data["entry_records"]}
        assert records[1] == {"entry_id": 1, "w": 3, "l": 2, "d": 1, "games": 6}
        assert records[2] == {"entry_id": 2, "w": 503, "l": 3, "d": 1, "games": 507}
        assert records[3] == {"entry_id": 3, "w": 0, "l": 501, "d": 0, "games": 501}

    # A reset must publish empty aggregates, even while entries remain.
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM league_results")
    reset = read_league_data(path)
    assert reset["totals"] == {"matches": 0, "rounds": 0, "games": 0}
    assert reset["entry_records"] == []


def test_recent_learner_record_is_complete_and_tracks_current_learner(tmp_path):
    path = str(tmp_path / "league.db")
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO league_entries (id,architecture,model_params,checkpoint_path,created_epoch) "
            "VALUES (?, 'resnet', '{}', '/fake.pt', 0)", [(1,), (2,), (3,)],
        )
        conn.execute(
            "INSERT INTO training_state "
            "(id,config_json,display_name,model_arch,algorithm_name,started_at,learner_entry_id) "
            "VALUES (1,'{}','Learner','resnet','ppo','2026-10-08',1)"
        )
        conn.executemany(
            "INSERT INTO league_results "
            "(epoch,entry_a_id,entry_b_id,match_type,num_games,wins_a,wins_b,draws) "
            "VALUES (?, ?, ?, 'calibration', ?, ?, ?, ?)",
            [(epoch, 1, 2, 4, 2, 1, 1) for epoch in range(11)]
            + [(10, 2, 1, 9, 3, 4, 2)]
            + [(999, 2, 3, 1, 1, 0, 0)] * 501,
        )
    data = read_league_data(path)
    assert all(row["entry_a_id"] == 2 and row["entry_b_id"] == 3 for row in data["results"])
    assert data["learner_recent_record"] == {"entry_id": 1, "w": 24, "l": 13, "d": 12, "rounds": 10}
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE training_state SET learner_entry_id = 3")
    assert read_league_data(path)["learner_recent_record"] == {
        "entry_id": 3, "w": 0, "l": 501, "d": 0, "rounds": 1,
    }
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM league_results")
    assert read_league_data(path)["learner_recent_record"] == {
        "entry_id": 3, "w": 0, "l": 0, "d": 0, "rounds": 0,
    }
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE training_state SET learner_entry_id = 999")
    assert read_league_data(path)["learner_recent_record"] is None


def test_feed_and_lifetime_records_share_one_read_snapshot(tmp_path, monkeypatch):
    path = str(tmp_path / "league.db")
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO league_entries (id,architecture,model_params,checkpoint_path,created_epoch) "
            "VALUES (?, 'resnet', '{}', '/fake.pt', 0)", [(1,), (2,)],
        )
    connect = league_module._connect

    def connect_with_concurrent_writer(db_path):
        conn = connect(db_path)
        written = False

        def after_recent_feed(sql):
            nonlocal written
            if sql.startswith("SELECT COUNT(*)") and not written:
                written = True
                with sqlite3.connect(db_path) as writer:
                    writer.execute(
                        "INSERT INTO league_results "
                        "(epoch,entry_a_id,entry_b_id,match_type,num_games,wins_a,wins_b,draws) "
                        "VALUES (1,1,2,'calibration',1,1,0,0)"
                    )

        conn.set_trace_callback(after_recent_feed)
        return conn

    monkeypatch.setattr(league_module, "_connect", connect_with_concurrent_writer)
    data = read_league_data(path)
    assert data["results"] == []
    assert data["entry_records"] == []
    assert data["totals"]["matches"] == 0
    monkeypatch.setattr(league_module, "_connect", connect)
    assert read_league_data(path)["totals"]["matches"] == 1
