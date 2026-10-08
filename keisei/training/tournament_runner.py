"""Tournament worker sidecar: claims batches of pairings and runs them
concurrently via ConcurrentMatchPool.

Usage:
    python -m keisei.training.tournament_runner \\
        --config keisei-league.toml \\
        --db-path data/keisei-league.db \\
        --league-dir checkpoints/league/league \\
        --worker-id worker-0 \\
        --device cuda:1

The runner is a thin CLI wrapper around TournamentWorker, which is
unit-testable via injected ``pool`` and ``vecenv_factory`` arguments.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch

from keisei.config import ConcurrencyConfig, DynamicConfig, RoleEloConfig, load_config
from keisei.db.tournament_queue import (
    ClaimedPairing,
    claim_next_pairings_batch,
    mark_pairing_done,
    reset_stale_playing,
    write_worker_heartbeat,
)
from keisei.training.concurrent_matches import (
    ConcurrentMatchPool,
    MatchResult,
    RoundStats,
)
from keisei.training.dynamic_trainer import DynamicTrainer
from keisei.training.match_scheduler import is_training_match
from keisei.training.match_utils import release_models
from keisei.training.opponent_store import (
    EntryStatus,
    OpponentEntry,
    OpponentStore,
    Role,
    compute_elo_update,
)
from keisei.training.role_elo import RoleEloTracker
from keisei.training.tournament import majority_wins_result

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
HEARTBEAT_INTERVAL_SECONDS = 10.0
# Multiplier on parallel_matches for per-iteration claim size.  Gives the
# pool's slot back-fill logic a pool of spare pairings to draw from when
# early-finishing slots would otherwise idle.
BATCH_OVERCLAIM_FACTOR = 2


class TournamentWorker:
    """Main loop for a single tournament worker process.

    Claims up to ``BATCH_OVERCLAIM_FACTOR × concurrency.parallel_matches``
    pending pairings per iteration, plays them concurrently via
    ``ConcurrentMatchPool.run_round``, then records results and updates Elo.
    """

    def __init__(
        self, *,
        db_path: str,
        league_dir: str,
        worker_id: str,
        device: str,
        concurrency: ConcurrencyConfig,
        games_per_match: int = 3,
        max_ply: int = 512,
        max_staleness_epochs: int = 50,
        k_factor: float = 16.0,
        stop_event: threading.Event | None = None,
        pool: ConcurrentMatchPool | None = None,
        vecenv_factory: Callable[[], Any] | None = None,
        dynamic_config: DynamicConfig | None = None,
        learner_lr: float = 2e-4,
        role_elo_config: RoleEloConfig | None = None,
    ) -> None:
        self.db_path = db_path
        self.worker_id = worker_id
        self.device = torch.device(device)
        self.concurrency = concurrency
        self.games_per_match = games_per_match
        self.max_ply = max_ply
        self.max_staleness_epochs = max_staleness_epochs
        self.k_factor = k_factor
        self._stop_event = stop_event or threading.Event()
        self._vecenv_factory = vecenv_factory
        self._pairings_done = 0
        self._last_heartbeat = 0.0
        self._pool = pool if pool is not None else ConcurrentMatchPool(concurrency)

        self.store = OpponentStore(db_path=db_path, league_dir=league_dir)
        self.role_elo_tracker = RoleEloTracker(self.store, role_elo_config or RoleEloConfig())
        self.dynamic_trainer = (
            DynamicTrainer(self.store, dynamic_config, learner_lr)
            if dynamic_config is not None and dynamic_config.training_enabled else None
        )

    def _maybe_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            write_worker_heartbeat(
                self.db_path, worker_id=self.worker_id,
                pid=os.getpid(), device=str(self.device),
                pairings_done=self._pairings_done,
            )
            self._last_heartbeat = now

    def _startup_sweep(self) -> None:
        n = reset_stale_playing(self.db_path, worker_id=self.worker_id)
        if n > 0:
            logger.info(
                "Startup sweep: reset %d stale 'playing' pairings for worker %s",
                n, self.worker_id,
            )

    def run(self) -> None:
        """Main loop: batch-claim → run_round → record → heartbeat → repeat."""
        logger.info(
            "Tournament worker %s starting on %s (parallel=%d, total_envs=%d)",
            self.worker_id, self.device,
            self.concurrency.parallel_matches, self.concurrency.total_envs,
        )
        self._startup_sweep()
        self._maybe_heartbeat()

        if self._vecenv_factory is None:
            from shogi_gym import VecEnv

            def _default_factory() -> Any:
                return VecEnv(  # type: ignore[call-arg]  # PyO3 kwargs are absent from the native stub.
                    num_envs=self.concurrency.total_envs,
                    max_ply=self.max_ply,
                    observation_mode="katago", action_mode="spatial",
                )

            self._vecenv_factory = _default_factory
        vecenv = self._vecenv_factory()

        batch_size = BATCH_OVERCLAIM_FACTOR * self.concurrency.parallel_matches

        try:
            while not self._stop_event.is_set():
                self._maybe_heartbeat()
                batch = claim_next_pairings_batch(
                    self.db_path,
                    worker_id=self.worker_id,
                    limit=batch_size,
                    current_epoch=self.store.get_current_epoch(),
                    max_staleness_epochs=self.max_staleness_epochs,
                )
                if not batch:
                    self._stop_event.wait(POLL_INTERVAL_SECONDS)
                    continue
                self._play_batch(vecenv, batch)
        finally:
            logger.info(
                "Tournament worker %s stopping (%d pairings completed)",
                self.worker_id, self._pairings_done,
            )

    def _play_batch(
        self, vecenv: Any, batch: list[ClaimedPairing],
    ) -> None:
        """Run one batch of claims through the pool, record results, mark queue."""
        current_epoch = self.store.get_current_epoch()
        # Keep claims + pairings in index-parallel lists.  Several claims in
        # one batch may share the same (entry_a_id, entry_b_id) when the
        # dispatcher enqueues duplicate pairs, so we can't key by IDs — we
        # match results back by OpponentEntry object identity below.
        claims_in_order: list[ClaimedPairing] = []
        pairings: list[tuple[OpponentEntry, OpponentEntry]] = []
        for claim in batch:
            entry_a = self.store.get_entry(claim.entry_a_id)
            entry_b = self.store.get_entry(claim.entry_b_id)
            if entry_a is None or entry_b is None:
                logger.warning(
                    "Entry disappeared for claim %d (a=%s b=%s) — marking failed",
                    claim.id, claim.entry_a_id, claim.entry_b_id,
                )
                mark_pairing_done(self.db_path, claim.id, status="failed")
                continue
            pairings.append((entry_a, entry_b))
            claims_in_order.append(claim)

        if not pairings:
            return

        max_cached = self.concurrency.max_resident_models

        def _load_fn(entry: OpponentEntry) -> torch.nn.Module:
            return self.store.load_opponent_cached(
                entry, device=str(self.device), max_cached=max_cached,
            )

        def _release_fn(model_a: Any, model_b: Any) -> None:
            # With an LRU cache, the same model object is shared across slots
            # (entry 1 appears in pairings (1,2) and (1,3)).  release_models()
            # moves the shared object off GPU and would crash other slots
            # still using it.  Flush the CUDA allocator for freed blocks
            # instead; the cache manages model lifecycle and VRAM.
            if max_cached > 0:
                if self.device.type == "cuda":
                    with torch.cuda.device(self.device):
                        torch.cuda.empty_cache()
            else:
                release_models(model_a, model_b, device_type=self.device.type)

        try:
            results, stats = self._pool.run_round(
                vecenv,
                pairings,
                load_fn=_load_fn,
                release_fn=_release_fn,
                device=self.device,
                games_per_match=self.games_per_match,
                max_ply=self.max_ply,
                stop_event=self._stop_event,
                epoch=current_epoch,
                trainable_fn=self._is_trainable_match if self.dynamic_trainer is not None else None,
            )
        except Exception:
            logger.exception(
                "run_round raised — marking all %d claimed pairings failed",
                len(claims_in_order),
            )
            for claim in claims_in_order:
                mark_pairing_done(self.db_path, claim.id, status="failed")
            return

        self._record_results(
            results, pairings, claims_in_order, stats,
        )

    def _record_results(
        self,
        results: list[MatchResult],
        pairings: list[tuple[OpponentEntry, OpponentEntry]],
        claims_in_order: list[ClaimedPairing],
        stats: RoundStats,
    ) -> None:
        """Write Elo + result rows for each MatchResult; mark queue status.

        Matches each MatchResult back to its claim via OpponentEntry object
        identity so duplicate (entry_a_id, entry_b_id) pairs in a single
        batch are handled correctly.  Claimed pairings that have no
        corresponding result (e.g. pool-side load failure, early stop) are
        marked 'failed' so the queue row has a terminal status.

        Each result row is tagged with the claim's ``enqueued_epoch`` rather
        than the worker's current_epoch — a single batch may straddle
        multiple rounds, and the trainer epoch may have advanced since the
        pairing was queued.  Using ``enqueued_epoch`` keeps
        ``league_results`` / ``head_to_head`` / ``elo_history`` aligned with
        ``tournament_pairing_queue`` per round.
        """
        unmatched_indices: set[int] = set(range(len(pairings)))
        for result in results:
            match_idx: int | None = None
            for i in unmatched_indices:
                if (pairings[i][0] is result.entry_a
                        and pairings[i][1] is result.entry_b):
                    match_idx = i
                    break
            if match_idx is None:
                logger.warning(
                    "Result for (%d,%d) has no matching claim in batch — skipping",
                    result.entry_a.id, result.entry_b.id,
                )
                continue
            unmatched_indices.discard(match_idx)
            claim = claims_in_order[match_idx]
            total = result.a_wins + result.b_wins + result.draws
            if total == 0:
                mark_pairing_done(self.db_path, claim.id, status="failed")
                continue
            try:
                self._write_match_result(result, claim.enqueued_epoch)
                mark_pairing_done(self.db_path, claim.id, status="done")
                self._pairings_done += 1
            except Exception:
                logger.exception(
                    "Failed to record result for %s vs %s — marking pairing failed",
                    result.entry_a.display_name, result.entry_b.display_name,
                )
                mark_pairing_done(self.db_path, claim.id, status="failed")
                continue
            # Persist per-game feature rows (drives StyleProfiler later).
            # Independent of match-result write: feature failure must not
            # un-mark the pairing or rewind Elo.
            self._write_game_features(result)
            # Match records retain the pre-update counts. Learning errors cannot
            # undo a completed pairing or its result; the trainer handles them.
            self._train_dynamic_entries(result)

        for i in unmatched_indices:
            claim = claims_in_order[i]
            logger.warning(
                "Pairing %d (%d vs %d) had no result from run_round — "
                "marking failed",
                claim.id, claim.entry_a_id, claim.entry_b_id,
            )
            mark_pairing_done(self.db_path, claim.id, status="failed")

        if stats.round_duration_s > 0:
            logger.info(
                "Batch complete: %d/%d pairings, %d games in %.1fs",
                stats.pairings_completed, stats.pairings_requested,
                stats.total_games, stats.round_duration_s,
            )

    @staticmethod
    def _is_trainable_match(a: OpponentEntry, b: OpponentEntry) -> bool:
        return is_training_match(a, b) and any(
            entry.role == Role.DYNAMIC and entry.training_enabled
            and entry.status == EntryStatus.ACTIVE for entry in (a, b)
        )

    def _train_dynamic_entries(self, result: MatchResult) -> None:
        trainer = self.dynamic_trainer
        if trainer is None or result.rollout is None:
            return
        current_a = self.store.get_entry(result.entry_a.id)
        current_b = self.store.get_entry(result.entry_b.id)
        if current_a is None or current_b is None or not is_training_match(current_a, current_b):
            return
        for side, entry in enumerate((current_a, current_b)):
            if (entry.role != Role.DYNAMIC or not entry.training_enabled
                    or entry.status != EntryStatus.ACTIVE):
                continue
            trainer.record_match(entry.id, result.rollout, side)
            if (trainer.should_update(entry.id) and not trainer.is_rate_limited()
                    and not trainer.is_gpu_backpressured(str(self.device))):
                try:
                    trainer.update(entry, str(self.device))
                except Exception:
                    logger.exception("Dynamic sidecar update failed for entry %d", entry.id)

    def _write_game_features(self, result: MatchResult) -> None:
        """Persist completed per-game feature rows for one match."""
        tracker = result.feature_tracker
        if tracker is None or not tracker.completed_rows:
            return
        try:
            from keisei.db import write_game_features
            rows = [r.to_dict() for r in tracker.completed_rows]
            write_game_features(self.db_path, rows)
        except Exception:
            logger.warning("Failed to write game features", exc_info=True)

    def _write_match_result(self, result: MatchResult, epoch: int) -> None:
        entry_a_id = result.entry_a.id
        entry_b_id = result.entry_b.id
        # Reserve the SQLite writer before reading ratings. Other sidecars
        # must see this result's committed ratings before computing theirs.
        with self.store.transaction(immediate=True):
            current_a = self.store.get_entry(entry_a_id)
            current_b = self.store.get_entry(entry_b_id)
            if current_a is None or current_b is None:
                raise RuntimeError(
                    f"Entry disappeared between claim and record "
                    f"(a={entry_a_id}, b={entry_b_id})",
                )
            result_score = majority_wins_result(
                result.a_wins, result.b_wins, result.draws,
            )
            new_a_elo, new_b_elo = compute_elo_update(
                current_a.elo_rating, current_b.elo_rating,
                result=result_score, k=self.k_factor,
            )
            context = RoleEloTracker.determine_match_context(current_a, current_b)
            column_a, column_b = self.role_elo_tracker.columns_for_context(current_a, current_b, context)
            column_b = column_b or column_a
            self.role_elo_tracker.update_from_result(current_a, current_b, result_score, context)
            updated_a = self.store.get_entry(entry_a_id)
            updated_b = self.store.get_entry(entry_b_id)
            assert updated_a is not None and updated_b is not None
            self.store.record_result(
                epoch=epoch,
                entry_a_id=entry_a_id,
                entry_b_id=entry_b_id,
                wins_a=result.a_wins,
                wins_b=result.b_wins,
                draws=result.draws,
                match_type="train" if is_training_match(current_a, current_b) else "calibration",
                role_a=current_a.role,
                role_b=current_b.role,
                elo_before_a=getattr(current_a, column_a.value),
                elo_after_a=getattr(updated_a, column_a.value),
                elo_before_b=getattr(current_b, column_b.value),
                elo_after_b=getattr(updated_b, column_b.value),
                training_updates_a=current_a.update_count,
                training_updates_b=current_b.update_count,
            )
            self.store.update_elo(entry_a_id, new_a_elo, epoch=epoch)
            self.store.update_elo(entry_b_id, new_b_elo, epoch=epoch)
        logger.info(
            "  %s vs %s — %dW %dL %dD (Elo: %.0f→%.0f / %.0f→%.0f)",
            current_a.display_name, current_b.display_name,
            result.a_wins, result.b_wins, result.draws,
            current_a.elo_rating, new_a_elo,
            current_b.elo_rating, new_b_elo,
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tournament worker sidecar")
    p.add_argument("--config", required=True, help="Path to league TOML config")
    p.add_argument("--db-path", required=True)
    p.add_argument("--league-dir", required=True)
    p.add_argument("--worker-id", required=True)
    p.add_argument("--device", default=None,
                   help="Override config.league.tournament_device")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: Any) -> None:
        logger.info("Received signal %d, stopping gracefully", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    cfg = load_config(Path(args.config))
    if cfg.league is None:
        raise SystemExit("Config has no [league] section — nothing to do")

    device = args.device or cfg.league.tournament_device or "cuda:1"

    worker = TournamentWorker(
        db_path=args.db_path,
        league_dir=args.league_dir,
        worker_id=args.worker_id,
        device=device,
        concurrency=cfg.league.concurrency,
        games_per_match=cfg.league.tournament_games_per_match,
        max_ply=cfg.training.max_ply,
        max_staleness_epochs=cfg.league.max_staleness_epochs,
        k_factor=cfg.league.tournament_k_factor,
        stop_event=stop_event,
        dynamic_config=cfg.league.dynamic,
        learner_lr=float(cfg.training.algorithm_params.get("learning_rate", 2e-4)),
        role_elo_config=cfg.league.elo,
    )
    worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
