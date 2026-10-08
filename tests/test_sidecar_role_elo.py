"""Sidecars must update contextual ratings and preserve concurrent match results."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from torch import nn

from keisei.config import ConcurrencyConfig, MatchSchedulerConfig, RoleEloConfig
from keisei.db import init_db
from keisei.training.concurrent_matches import MatchResult
from keisei.training.match_scheduler import MatchScheduler
from keisei.training.opponent_store import EloColumn, OpponentStore, Role, compute_elo_update
from keisei.training.tournament import LeagueTournament
from keisei.training.tournament_runner import TournamentWorker

pytestmark = pytest.mark.integration


@pytest.fixture
def workers(tmp_path: Path):
    db_path = str(tmp_path / "league.db")
    league_dir = str(tmp_path / "league")
    init_db(db_path)
    store = OpponentStore(db_path, league_dir)
    role_config = RoleEloConfig(frontier_k=6.0, dynamic_k=10.0, recent_k=14.0)
    created = []

    def make_worker():
        worker = TournamentWorker(
            db_path=db_path, league_dir=league_dir, worker_id=str(len(created)),
            device="cpu", concurrency=ConcurrencyConfig(), k_factor=16.0,
            role_elo_config=role_config,
        )
        created.append(worker)
        return worker

    yield store, make_worker
    for worker in created:
        worker.store.close()
    store.close()


def _record(worker, result, epoch, in_process):
    if in_process:
        tournament = LeagueTournament(
            worker.store, MatchScheduler(MatchSchedulerConfig()), device="cpu",
            role_elo_tracker=worker.role_elo_tracker,
        )
        tournament._record_match_result(
            epoch=epoch, entry_a_id=result.entry_a.id, entry_b_id=result.entry_b.id,
            a_wins=result.a_wins, b_wins=result.b_wins, draws=result.draws, rollout=None,
        )
    else:
        worker._write_match_result(result, epoch)


@pytest.mark.parametrize("in_process", [False, True])
@pytest.mark.parametrize(
    ("role_a", "role_b", "column_a", "column_b", "k", "match_type"),
    [
        (Role.DYNAMIC, Role.DYNAMIC, EloColumn.DYNAMIC, EloColumn.DYNAMIC, 10.0, "train"),
        (Role.DYNAMIC, Role.RECENT_FIXED, EloColumn.DYNAMIC, EloColumn.RECENT, 10.0, "train"),
        (Role.RECENT_FIXED, Role.DYNAMIC, EloColumn.RECENT, EloColumn.DYNAMIC, 14.0, "train"),
        (Role.FRONTIER_STATIC, Role.DYNAMIC, EloColumn.FRONTIER, EloColumn.FRONTIER, 6.0, "calibration"),
        (Role.RECENT_FIXED, Role.RECENT_FIXED, EloColumn.RECENT, EloColumn.RECENT, 14.0, "calibration"),
    ],
)
def test_sidecar_records_contextual_ratings(workers, role_a, role_b, column_a, column_b, k, match_type, in_process):
    store, make_worker = workers
    a = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=role_a)
    b = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=role_b)
    store.update_elo(a.id, 1400.0, epoch=1)
    store.update_elo(b.id, 1600.0, epoch=1)
    store.update_role_elo(a.id, column_a, 1100.0)
    store.update_role_elo(b.id, column_b, 900.0)
    worker = make_worker()

    _record(worker, MatchResult(a, b, 3, 0, 0, None), 2, in_process)

    expected_a, expected_b = compute_elo_update(1100.0, 900.0, 1.0, k)
    assert getattr(store.get_entry(a.id), column_a.value) == pytest.approx(expected_a)
    assert getattr(store.get_entry(b.id), column_b.value) == pytest.approx(expected_b)
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT match_type, elo_before_a, elo_after_a, elo_before_b, elo_after_b FROM league_results",
        ).fetchone()
    assert row[0] == match_type
    assert row[1:] == pytest.approx((1100.0, expected_a, 900.0, expected_b))


def test_sidecar_rating_failure_rolls_back_entire_result(workers):
    store, make_worker = workers
    a = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=Role.DYNAMIC)
    b = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=Role.DYNAMIC)
    worker = make_worker()

    with patch.object(worker.store, "update_role_elo", side_effect=RuntimeError("role write failed")):
        with pytest.raises(RuntimeError, match="role write failed"):
            worker._write_match_result(MatchResult(a, b, 3, 0, 0, None), epoch=2)

    assert store.get_entry(a.id).elo_rating == 1000.0
    assert store.get_entry(a.id).games_played == 0
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM league_results").fetchone()[0] == 0


@pytest.mark.parametrize("in_process", [False, True])
def test_two_sidecar_stores_compose_updates_for_shared_entries(workers, in_process):
    store, make_worker = workers
    a = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=Role.DYNAMIC)
    b = store.add_entry(nn.Linear(1, 1), "test", {}, epoch=1, role=Role.DYNAMIC)
    first, second = make_worker(), make_worker()
    first_read = threading.Event()
    second_read = threading.Event()
    release_first = threading.Event()
    read_first = first.store.get_entry
    read_second = second.store.get_entry

    def pause_first(entry_id):
        entry = read_first(entry_id)
        if entry_id == a.id and not first_read.is_set():
            first_read.set()
            assert release_first.wait(5)
        return entry

    def observe_second(entry_id):
        entry = read_second(entry_id)
        second_read.set()
        return entry

    result = MatchResult(a, b, 3, 0, 0, None)
    with patch.object(first.store, "get_entry", side_effect=pause_first), patch.object(
        second.store, "get_entry", side_effect=observe_second,
    ), ThreadPoolExecutor(max_workers=2) as pool:
        task_a = pool.submit(_record, first, result, 2, in_process)
        assert first_read.wait(5)
        task_b = pool.submit(_record, second, result, 3, in_process)
        # A correct writer reservation prevents the second rating read until
        # the first transaction commits. Before the fix both read 1000 here.
        second_read.wait(0.5)
        release_first.set()
        task_a.result(timeout=5)
        task_b.result(timeout=5)

    composite_k = 10.0 if in_process else 16.0
    composite_a, composite_b = compute_elo_update(1000.0, 1000.0, 1.0, composite_k)
    composite_a, composite_b = compute_elo_update(composite_a, composite_b, 1.0, composite_k)
    dynamic_a, dynamic_b = compute_elo_update(1000.0, 1000.0, 1.0, 10.0)
    dynamic_a, dynamic_b = compute_elo_update(dynamic_a, dynamic_b, 1.0, 10.0)
    assert store.get_entry(a.id).elo_rating == pytest.approx(composite_a)
    assert store.get_entry(b.id).elo_rating == pytest.approx(composite_b)
    assert store.get_entry(a.id).elo_dynamic == pytest.approx(dynamic_a)
    assert store.get_entry(b.id).elo_dynamic == pytest.approx(dynamic_b)
    assert store.get_entry(a.id).games_played == 6
