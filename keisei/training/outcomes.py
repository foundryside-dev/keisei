"""Episode outcome supervision, separate from the on-policy actor rollout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray


@dataclass(frozen=True)
class GameOutcomeBatch:
    """CPU observations and mover-relative W/D/L labels from completed games."""

    observations: torch.Tensor
    value_categories: torch.Tensor


class GameOutcomeTracker:
    """Keep selected observations until their game's actual outcome is known.

    Unfinished games survive actor rollout boundaries. Truncated games are
    discarded, and only ended environment lanes are cleared at an auto-reset.
    Historical observations supervise only the value head; actions and policy
    likelihoods are never retained or replayed.
    """

    def __init__(self, num_envs: int) -> None:
        if num_envs <= 0:
            raise ValueError("num_envs must be positive")
        self.num_envs = num_envs
        self._histories: list[list[tuple[torch.Tensor, int]]] = [[] for _ in range(num_envs)]
        self._completed_observations: list[torch.Tensor] = []
        self._completed_categories: list[int] = []

    def _validate_players(self, players: NDArray[np.integer[Any]]) -> None:
        if players.shape != (self.num_envs,) or not np.isin(players, [0, 1]).all():
            raise ValueError("players must contain one color (0 or 1) per environment")

    def record(
        self, observations: torch.Tensor, players: NDArray[np.integer[Any]],
        mask: torch.Tensor | None = None,
    ) -> None:
        """Snapshot each selected pre-move observation in its mover's frame."""
        self._validate_players(players)
        if observations.ndim < 2 or observations.shape[0] != self.num_envs:
            raise ValueError("observations must contain one observation per environment")
        if mask is not None and (mask.shape != (self.num_envs,) or mask.dtype != torch.bool):
            raise ValueError("mask must contain one boolean per environment")
        indices = (
            mask.detach().cpu().nonzero(as_tuple=True)[0].tolist()
            if mask is not None else list(range(self.num_envs))
        )
        observations_cpu = observations.detach().cpu()
        for env_id in indices:
            # CPU inputs can be reused or mutated by callers too. Own each
            # lane's snapshot rather than retaining a view of the input batch.
            self._histories[env_id].append((observations_cpu[env_id].clone(), int(players[env_id])))

    def resolve(
        self, rewards: torch.Tensor, terminated: torch.Tensor, truncated: torch.Tensor,
        pre_players: NDArray[np.integer[Any]],
    ) -> None:
        """Assign completed-game labels using raw last-mover reward signs."""
        self._validate_players(pre_players)
        for name, tensor in (("rewards", rewards), ("terminated", terminated), ("truncated", truncated)):
            if tensor.shape != (self.num_envs,):
                raise ValueError(f"{name} must contain one value per environment")
        rewards_cpu = rewards.detach().cpu()
        if not torch.isfinite(rewards_cpu).all():
            raise ValueError("Game outcome rewards must be finite")
        terminated_cpu = terminated.detach().bool().cpu()
        truncated_cpu = truncated.detach().bool().cpu()
        ended = (terminated_cpu | truncated_cpu).nonzero(as_tuple=True)[0].tolist()
        for env_id in ended:
            if terminated_cpu[env_id]:
                reward = float(rewards_cpu[env_id])
                last_mover = int(pre_players[env_id])
                for observation, player in self._histories[env_id]:
                    own_reward = reward if player == last_mover else -reward
                    category = 0 if own_reward > 0 else 2 if own_reward < 0 else 1
                    self._completed_observations.append(observation)
                    self._completed_categories.append(category)
            self._histories[env_id].clear()

    def pop_completed(self) -> GameOutcomeBatch | None:
        """Consume completed observations once, retaining unfinished games."""
        if not self._completed_observations:
            return None
        batch = GameOutcomeBatch(
            observations=torch.stack(self._completed_observations),
            value_categories=torch.tensor(self._completed_categories, dtype=torch.long),
        )
        self._completed_observations.clear()
        self._completed_categories.clear()
        return batch
