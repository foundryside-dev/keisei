"""Only one process may recover games and publish a database's heartbeat."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_second_runner_process_cannot_acquire_database(tmp_path: Path) -> None:
    from keisei.showcase.ownership import acquire_showcase_ownership

    db = tmp_path / "showcase.db"
    with acquire_showcase_ownership(str(db)):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; from keisei.showcase.ownership import acquire_showcase_ownership; "
                "\nwith acquire_showcase_ownership(sys.argv[1]): print('acquired')",
                str(db),
            ],
            capture_output=True, text=True, timeout=5,
        )
    assert result.returncode != 0
    assert "already owns database" in result.stderr
    assert result.stdout == ""


def test_owner_crash_releases_lock_without_removing_lock_file(tmp_path: Path) -> None:
    from keisei.showcase.ownership import acquire_showcase_ownership

    db = tmp_path / "showcase.db"
    child = subprocess.Popen(
        [
            sys.executable, "-c",
            "import sys; from keisei.showcase.ownership import acquire_showcase_ownership; "
            "\nwith acquire_showcase_ownership(sys.argv[1]): "
            "print('ready', flush=True); sys.stdin.read()",
            str(db),
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeError, match="already owns database"):
            with acquire_showcase_ownership(str(db)):
                pytest.fail("second owner entered while the original process lived")
        lock_file = Path(f"{db}.showcase.lock")
        inode = lock_file.stat().st_ino
        child.kill()
        child.wait(timeout=5)
        with acquire_showcase_ownership(str(db)):
            assert lock_file.stat().st_ino == inode
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_alias_and_second_instance_share_persistent_lock(tmp_path: Path) -> None:
    from keisei.showcase.ownership import acquire_showcase_ownership

    db = tmp_path / "showcase.db"
    db.touch()
    alias = tmp_path / "alias.db"
    alias.symlink_to(db)
    lock_file = Path(f"{db}.showcase.lock")
    with acquire_showcase_ownership(str(db)):
        inode = lock_file.stat().st_ino
        with pytest.raises(RuntimeError, match="already owns database"):
            with acquire_showcase_ownership(str(alias)):
                pytest.fail("symlink bypassed database ownership")
    assert lock_file.exists()
    with acquire_showcase_ownership(str(alias)):
        assert lock_file.stat().st_ino == inode
    assert not Path(f"{alias}.showcase.lock").exists()


def test_second_runner_stops_before_recovery_or_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from keisei.showcase.ownership import acquire_showcase_ownership
    from keisei.showcase.runner import ShowcaseRunner

    db = str(tmp_path / "showcase.db")
    runner = ShowcaseRunner(db, auto_showcase_enabled=False)
    # Returning immediately avoids starting a real game even on the broken
    # path; ownership must still reject this attempt before touching state.
    runner.stop()
    cleanup = MagicMock()
    heartbeat = MagicMock()
    monkeypatch.setattr(runner, "_startup_cleanup", cleanup)
    monkeypatch.setattr(runner, "_write_heartbeat", heartbeat)
    monkeypatch.setattr("keisei.showcase.runner.enforce_cpu_only", lambda _: None)
    with acquire_showcase_ownership(db):
        with pytest.raises(RuntimeError, match="already owns database"):
            runner.run()
    cleanup.assert_not_called()
    heartbeat.assert_not_called()
