"""DynamicTrainer — small PPO updates for Dynamic entries from league match data."""

from __future__ import annotations

import fcntl
import logging
import threading
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import torch

from keisei.training.katago_ppo import ppo_clip_loss
from keisei.training.opponent_store import EntryStatus, Role
from keisei.training.policy import masked_categorical
from keisei.training.value_adapter import wdl_cross_entropy_loss

if TYPE_CHECKING:
    from keisei.config import DynamicConfig
    from keisei.training.opponent_store import OpponentEntry, OpponentStore

logger = logging.getLogger(__name__)


@dataclass
class MatchRollout:
    """Replay data from a league match for Dynamic entry training.

    Step dimension is VARIABLE — depends on game length, not a fixed value.
    All tensors stored on CPU to avoid GPU memory pressure.
    """

    observations: torch.Tensor  # (steps, num_envs, obs_channels, 9, 9)
    actions: torch.Tensor  # (steps, num_envs)
    rewards: torch.Tensor  # (steps, num_envs)
    dones: torch.Tensor  # (steps, num_envs)
    legal_masks: torch.Tensor  # (steps, num_envs, action_space)
    perspective: torch.Tensor  # (steps, num_envs) — 0=player_A, 1=player_B
    terminated: torch.Tensor | None = None
    log_probs: torch.Tensor | None = None
    checkpoint_versions: tuple[str | None, str | None] = (None, None)


class DynamicTrainer:
    """Small PPO updates for Dynamic entries from league match data.

    Matches hold immutable inference snapshots. Updates serialize within a
    trainer and across worker processes; complete weights and optimizer state
    publish atomically, and stale snapshot data is discarded before training.
    """

    def __init__(
        self,
        store: OpponentStore,
        config: DynamicConfig,
        learner_lr: float,
    ) -> None:
        self.store = store
        self.config = config
        self.learner_lr = learner_lr

        self._match_counts: dict[int, int] = {}
        self._update_timestamps: list[float] = []
        self._optimizers: dict[int, torch.optim.Adam] = {}
        self._disabled_entries: set[int] = set()
        self._rollout_buffers: dict[int, deque[tuple[MatchRollout, int]]] = {}
        self._error_counts: dict[int, int] = {}
        # Global inference-only fallback (§10.4)
        self._globally_disabled: bool = False
        self._global_error_timestamps: list[float] = []
        self._update_lock = threading.RLock()
        self._prepared_log_probs: torch.Tensor | None = None
        self._optimizer_versions: dict[int, str] = {}

    # ------------------------------------------------------------------
    # Record & query
    # ------------------------------------------------------------------

    def record_match(self, entry_id: int, rollout: MatchRollout, side: int) -> None:
        """Record a match rollout for a Dynamic entry."""
        if entry_id in self._disabled_entries:
            return
        if entry_id not in self._rollout_buffers:
            self._rollout_buffers[entry_id] = deque(maxlen=self.config.max_buffer_depth)
        self._rollout_buffers[entry_id].append((rollout, side))
        self._match_counts[entry_id] = self._match_counts.get(entry_id, 0) + 1

    def should_update(self, entry_id: int) -> bool:
        """Check if enough matches have accumulated for an update."""
        if self._globally_disabled:
            return False
        if entry_id in self._disabled_entries:
            return False
        return self._match_counts.get(entry_id, 0) >= self.config.update_every_matches

    def is_rate_limited(self) -> bool:
        """Check if updates are rate-limited (too many in the last 60 seconds).

        This also serves as the plan's §10.4 "hard cap checkpoint writes per
        minute" — each update writes weights (and periodically optimizer), so
        capping updates effectively caps checkpoint writes.
        """
        now = time.monotonic()
        cutoff = now - 60.0
        self._update_timestamps = [t for t in self._update_timestamps if t >= cutoff]
        return len(self._update_timestamps) >= self.config.max_updates_per_minute

    @property
    def is_globally_disabled(self) -> bool:
        """True if Dynamic training has been globally disabled due to widespread errors."""
        return self._globally_disabled

    def is_gpu_backpressured(self, device: str) -> bool:
        """True if GPU memory usage exceeds the backpressure threshold (§10.4)."""
        if not device.startswith("cuda") or not torch.cuda.is_available():
            return False
        dev = torch.device(device)
        reserved = torch.cuda.memory_reserved(dev)
        total = torch.cuda.get_device_properties(dev).total_memory
        if total == 0:
            return False
        utilization = reserved / total
        if utilization >= self.config.gpu_memory_backpressure:
            logger.info(
                "GPU backpressure: %.1f%% memory reserved (threshold %.0f%%)",
                utilization * 100,
                self.config.gpu_memory_backpressure * 100,
            )
            return True
        return False

    def _check_global_disable(self) -> None:
        """Check if errors across all entries exceed the global threshold (§10.4).

        When triggered, sets _globally_disabled = True, falling back to
        inference-only mode for all Dynamic entries.
        """
        now = time.monotonic()
        cutoff = now - self.config.global_error_window_seconds
        self._global_error_timestamps = [
            t for t in self._global_error_timestamps if t >= cutoff
        ]
        if len(self._global_error_timestamps) >= self.config.global_error_threshold:
            self._globally_disabled = True
            logger.error(
                "DynamicTrainer globally disabled: %d errors in %.0fs window "
                "(threshold %d). All Dynamic training stopped.",
                len(self._global_error_timestamps),
                self.config.global_error_window_seconds,
                self.config.global_error_threshold,
            )

    def get_update_stats(self, entry_id: int) -> tuple[int, str | None]:
        """Return (update_count, last_train_at) from the store entry."""
        entry = self.store.get_entry(entry_id)
        if entry is None:
            return (0, None)
        return (entry.update_count, entry.last_train_at)

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def _prepare_batch(
        self, entry_id: int, device: str
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Concatenate and filter rollouts by perspective, return flat tensors."""
        buffers: deque[tuple[MatchRollout, int]] | list[tuple[MatchRollout, int]] = self._rollout_buffers.get(entry_id, [])
        all_obs = []
        all_actions = []
        all_rewards = []
        all_dones = []
        all_legal_masks = []

        all_log_probs = []
        for rollout, side in buffers:
            assert rollout.perspective.shape == rollout.actions.shape, (
                f"perspective shape {rollout.perspective.shape} must match "
                f"actions shape {rollout.actions.shape}"
            )
            # Derive the result before filtering by side: the winner's final
            # move is often the only row carrying the engine's terminal reward.
            # Each finished game's entire trajectory receives its mover's result.
            targets = torch.zeros_like(rollout.rewards)
            valid = torch.zeros_like(rollout.dones, dtype=torch.bool)
            terminated = rollout.terminated if rollout.terminated is not None else rollout.dones
            for env in range(rollout.actions.shape[1]):
                start = 0
                for end in rollout.dones[:, env].bool().nonzero(as_tuple=True)[0].tolist():
                    if terminated[end, env]:
                        mover = rollout.perspective[end, env]
                        outcome = rollout.rewards[end, env]
                        same_side = rollout.perspective[start:end + 1, env] == mover
                        targets[start:end + 1, env] = torch.where(same_side, outcome, -outcome)
                        valid[start:end + 1, env] = True
                    start = end + 1
            # Ignore truncated and unfinished episodes; neither supplies W/D/L.
            mask = (rollout.perspective == side) & valid
            all_obs.append(rollout.observations[mask])
            all_actions.append(rollout.actions[mask])
            all_rewards.append(targets[mask])
            all_dones.append(valid[mask])
            all_legal_masks.append(rollout.legal_masks[mask])
            if rollout.log_probs is not None:
                all_log_probs.append(rollout.log_probs[mask])

        self._prepared_log_probs = (
            torch.cat(all_log_probs).to(device)
            if all_log_probs and len(all_log_probs) == len(all_obs) else None
        )

        if not all_obs:
            # Shape (0,) is sufficient: the only caller checks shape[0] == 0
            # and returns early.  No downstream code inspects higher dimensions.
            empty = torch.zeros(0)
            return empty, empty, empty, empty, empty

        return (
            torch.cat(all_obs).to(device),
            torch.cat(all_actions).to(device),
            torch.cat(all_rewards).to(device),
            torch.cat(all_dones).to(device),
            torch.cat(all_legal_masks).to(device),
        )

    def _get_or_create_optimizer(
        self, entry_id: int, model: torch.nn.Module
    ) -> torch.optim.Adam:
        """Get cached optimizer or create a new one (loading from store if available)."""
        if entry_id in self._optimizers:
            # Re-attach to new model parameters
            opt = self._optimizers[entry_id]
            # We need a fresh optimizer with the right params but the saved state
            new_opt = torch.optim.Adam(
                model.parameters(), lr=self.learner_lr * self.config.lr_scale
            )
            # Try to load state from the cached optimizer
            try:
                new_opt.load_state_dict(deepcopy(opt.state_dict()))
                # Move optimizer state to training device
                device = next(model.parameters()).device
                for state in new_opt.state.values():
                    for k, v in state.items():
                        if isinstance(v, torch.Tensor):
                            state[k] = v.to(device)
            except (ValueError, RuntimeError):
                logger.warning("Optimizer state mismatch for entry %d, resetting momentum", entry_id)
            return new_opt

        # Try loading from store
        saved_state = self.store.load_optimizer(entry_id)
        optimizer = torch.optim.Adam(
            model.parameters(), lr=self.learner_lr * self.config.lr_scale
        )
        if saved_state is not None:
            try:
                optimizer.load_state_dict(saved_state)
                # Move optimizer state to training device
                device = next(model.parameters()).device
                for state in optimizer.state.values():
                    for k, v in state.items():
                        if isinstance(v, torch.Tensor):
                            state[k] = v.to(device)
            except (ValueError, RuntimeError):
                logger.warning(
                    "Failed to load optimizer state for entry %d, starting fresh",
                    entry_id,
                )
        return optimizer

    def update(self, entry: OpponentEntry, device: str) -> bool:
        """Run a small PPO update on the Dynamic entry using accumulated match data.

        Returns True on success, False if an error was caught and handled.
        Raises on error when config.disable_on_error is False.

        Thread-safe: ``_update_lock`` serialises concurrent calls so that
        model weights are never half-updated when observed from another thread.
        """
        with self._update_lock:
            # Every sidecar owns its own trainer/store. A filesystem lock spans
            # the complete read/train/publish operation across worker processes.
            lock_path = Path(entry.checkpoint_path).with_suffix(".training.lock")
            with lock_path.open("a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    return self._update_guarded(entry, device)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _update_guarded(self, entry: OpponentEntry, device: str) -> bool:
        """Inner update with error handling — called under ``_update_lock``."""
        try:
            return self._update_inner(entry, device)
        except Exception:
            if not self.config.disable_on_error:
                raise
            # Clear stale rollout data to prevent training on corrupted buffers
            self._match_counts[entry.id] = 0
            self._rollout_buffers[entry.id] = deque(maxlen=self.config.max_buffer_depth)
            self._error_counts[entry.id] = self._error_counts.get(entry.id, 0) + 1
            self._global_error_timestamps.append(time.monotonic())
            logger.warning(
                "DynamicTrainer update failed for entry %d (error %d/%d)",
                entry.id,
                self._error_counts[entry.id],
                self.config.max_consecutive_errors,
                exc_info=True,
            )
            if self._error_counts[entry.id] >= self.config.max_consecutive_errors:
                self._disabled_entries.add(entry.id)
                logger.error(
                    "DynamicTrainer disabled entry %d after %d consecutive errors",
                    entry.id,
                    self.config.max_consecutive_errors,
                )
            self._check_global_disable()
            return False

    def _update_inner(self, entry: OpponentEntry, device: str) -> bool:
        """Internal update logic — may raise."""
        if (not self.config.training_enabled or self._globally_disabled
                or entry.id in self._disabled_entries):
            return False
        current = self.store.get_entry(entry.id)
        if (current is None or current.role != Role.DYNAMIC
                or not current.training_enabled or current.status != EntryStatus.ACTIVE):
            self._match_counts[entry.id] = 0
            self._rollout_buffers.pop(entry.id, None)
            return False
        model = self.store.load_opponent(current, device)
        revision = self.store.checkpoint_version(entry)
        # Other workers may have updated this entry while a match was running.
        # Never relabel an old behavior policy as the latest checkpoint.
        buffers = self._rollout_buffers.get(entry.id, deque())
        fresh = [(r, side) for r, side in buffers
                 if r.checkpoint_versions[side] in (None, revision)]
        self._rollout_buffers[entry.id] = deque(fresh, maxlen=self.config.max_buffer_depth)
        self._match_counts[entry.id] = len(fresh)
        if len(fresh) < self.config.update_every_matches:
            return False
        if self._optimizer_versions.get(entry.id, revision) != revision:
            self._optimizers.pop(entry.id, None)

        # Concatenate and filter rollouts by perspective
        all_obs, all_actions, all_rewards, all_dones, all_legal_masks = (
            self._prepare_batch(entry.id, device)
        )

        if all_obs.shape[0] == 0:
            self._match_counts[entry.id] = 0
            self._rollout_buffers[entry.id].clear()
            return False  # no completed, relevant games

        for name, tensor in (("observations", all_obs), ("outcomes", all_rewards)):
            if not torch.isfinite(tensor).all():
                raise ValueError(f"Dynamic training {name} must be finite")
        value_cats = torch.ones(all_obs.shape[0], dtype=torch.long, device=device)
        value_cats[all_rewards > 0] = 0
        value_cats[all_rewards < 0] = 2

        # Evaluation mode preserves the behavior policy's normalization and
        # dropout semantics, while gradients remain enabled during optimization.
        model.eval()
        old_log_probs = self._prepared_log_probs
        if old_log_probs is None:
            with torch.no_grad():
                output = model(all_obs)
                flat_logits = output.policy_logits.reshape(all_obs.shape[0], -1)
                old_log_probs = masked_categorical(flat_logits, all_legal_masks).log_prob(all_actions)
        if not torch.isfinite(old_log_probs).all():
            raise ValueError("Dynamic behavior log probabilities must be finite")

        # Train against a copied optimizer state; a failed multi-epoch update
        # must preserve the momentum associated with committed weights.
        optimizer = self._get_or_create_optimizer(entry.id, model)

        for _ in range(self.config.update_epochs_per_batch):
            indices = torch.randperm(all_obs.shape[0], device=device)
            output = model(all_obs[indices])
            flat_logits = output.policy_logits.reshape(len(indices), -1)
            new_log_probs = masked_categorical(
                flat_logits, all_legal_masks[indices],
            ).log_prob(all_actions[indices])
            if not torch.isfinite(output.value_logits).all():
                raise RuntimeError("Dynamic value logits must be finite")

            # Completed-game outcome supplies a signed return for every move.
            # Draws supervise W/D/L but have no signed policy preference.
            advantages = all_rewards[indices] * all_dones[indices].float()

            policy_loss = ppo_clip_loss(
                new_log_probs, old_log_probs[indices], advantages, clip_epsilon=0.2
            )
            value_loss = wdl_cross_entropy_loss(
                output.value_logits, value_cats[indices]
            )

            # Simplified objective: equal weights, no entropy bonus, no score
            # head.  Intentionally different from the main PPO learner — Dynamic
            # entries are short-lived opponents, not the primary agent.  The
            # missing entropy bonus means faster policy sharpening, which is
            # acceptable for opponent diversity but could be revisited for
            # long-lived Dynamic entries.
            loss = policy_loss + value_loss

            if not torch.isfinite(loss):
                raise RuntimeError("Dynamic training loss must be finite")
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), self.config.grad_clip, error_if_nonfinite=True,
            )
            optimizer.step()
            if any(not torch.isfinite(p).all() for p in model.parameters()):
                raise RuntimeError("Dynamic updated weights must be finite")

        # Another worker must receive the optimizer that produced these
        # weights. Publish both files and the update counter in one rollback-
        # safe transaction while retaining the cross-process writer lock.
        for state in optimizer.state.values():
            for key, value in state.items():
                if isinstance(value, torch.Tensor):
                    if not torch.isfinite(value).all():
                        raise RuntimeError("Dynamic optimizer state must be finite")
                    state[key] = value.cpu()
        with self.store.transaction():
            # The conditional UPDATE reserves SQLite's writer lock and checks
            # lifecycle flags atomically. Retirement cannot slip between this
            # decision and publication in another process.
            if not self.store.reserve_dynamic_update(entry.id):
                self._match_counts[entry.id] = 0
                self._rollout_buffers.pop(entry.id, None)
                return False
            self.store.save_weights(entry.id, model.state_dict())
            self.store.save_optimizer(entry.id, optimizer.state_dict())
            self.store.increment_update_count(entry.id)

        self._match_counts[entry.id] = 0
        self._rollout_buffers[entry.id] = deque(maxlen=self.config.max_buffer_depth)
        self._update_timestamps.append(time.monotonic())
        self._error_counts[entry.id] = 0
        self._optimizers[entry.id] = optimizer
        self._optimizer_versions[entry.id] = self.store.checkpoint_version(entry)

        return True
