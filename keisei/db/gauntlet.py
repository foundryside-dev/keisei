"""Gauntlet results table — periodic ladder evaluations against historical pool."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DDL = """
CREATE TABLE IF NOT EXISTS gauntlet_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch               INTEGER NOT NULL,
    entry_id            INTEGER NOT NULL REFERENCES league_entries(id),
    historical_slot     INTEGER NOT NULL,
    historical_entry_id INTEGER NOT NULL REFERENCES league_entries(id),
    wins                INTEGER NOT NULL,
    losses              INTEGER NOT NULL,
    draws               INTEGER NOT NULL,
    elo_before          REAL,
    elo_after           REAL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_gauntlet_epoch ON gauntlet_results(epoch);
"""


def read_gauntlet_history(
    db_path: str, *, before_epoch: int | None = None, limit: int = 5,
) -> dict[str, Any]:
    """Page complete distinct epochs, including history outside the live window."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if before_epoch is not None and (type(before_epoch) is not int or not 0 <= before_epoch <= 2**63 - 1):
        raise ValueError("before_epoch must be a nonnegative SQLite integer")
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        condition = "WHERE epoch < ?" if before_epoch is not None else ""
        params = (before_epoch, limit + 1) if before_epoch is not None else (limit + 1,)
        epochs = [row[0] for row in conn.execute(
            f"SELECT DISTINCT epoch FROM gauntlet_results {condition} ORDER BY epoch DESC LIMIT ?",
            params,
        )]
        selected = epochs[:limit]
        results = []
        if selected:
            placeholders = ",".join("?" for _ in selected)
            results = [dict(row) for row in conn.execute(
                f"SELECT * FROM gauntlet_results WHERE epoch IN ({placeholders}) "
                "ORDER BY epoch DESC, historical_slot, id", selected,
            )]
        return {
            "results": results,
            "next_before_epoch": selected[-1] if selected else None,
            "has_more": len(epochs) > limit,
        }
    finally:
        conn.close()
