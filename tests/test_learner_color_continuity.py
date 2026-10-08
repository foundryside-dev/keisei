"""Learner colors belong to games, including games spanning PPO epochs."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import torch

from keisei.config import AppConfig, LeagueConfig
from keisei.training import katago_loop
from keisei.training.katago_loop import KataGoTrainingLoop
from tests.test_katago_loop import _make_config, _make_mock_katago_vecenv


@pytest.fixture(autouse=True)
def cpu_threads():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


def _config(tmp_path: Path, epochs_per_seat: int) -> AppConfig:
    base = _make_config(tmp_path)
    params = dict(base.training.algorithm_params)
    params.update(epochs_per_batch=1, batch_size=8)
    return dataclasses.replace(
        base,
        training=dataclasses.replace(base.training, algorithm_params=params),
        model=dataclasses.replace(
            base.model,
            params={
                "num_blocks": 1, "channels": 8, "se_reduction": 2,
                "global_pool_channels": 4, "policy_channels": 2,
                "value_fc_size": 8, "score_fc_size": 8, "obs_channels": 50,
            },
        ),
        league=LeagueConfig(
            epochs_per_seat=epochs_per_seat, color_randomization=True,
            per_env_opponents=False,
        ),
    )


@pytest.mark.parametrize("epochs_per_seat", [50, 1])
def test_live_game_keeps_colors_and_turn_order_across_epochs(tmp_path, epochs_per_seat):
    env = _make_mock_katago_vecenv(alternate_players=True)
    loop = KataGoTrainingLoop(_config(tmp_path, epochs_per_seat), vecenv=env)
    sides = []
    learner_indices = []
    original = katago_loop.split_merge_step

    def capture(**kwargs):
        sides.append(kwargs["learner_side"].copy())
        result = original(**kwargs)
        learner_indices.append(result.learner_indices.tolist())
        return result

    # An odd epoch length leaves the opponent to move in one lane. Flushing
    # pending decisions for PPO must not transfer either lane to another color.
    with (
        patch.object(katago_loop, "split_merge_step", side_effect=capture),
        patch.object(
            katago_loop.np.random, "randint",
            side_effect=[np.array([0, 1], dtype=np.uint8), np.array([1, 0], dtype=np.uint8)],
        ) as random_colors,
    ):
        loop.run(num_epochs=2, steps_per_epoch=3)

    assert len(sides) == 6
    assert all(np.array_equal(side, [0, 1]) for side in sides)
    assert learner_indices == [[0], [1], [0], [1], [0], [1]]
    assert random_colors.call_count == 1
    env.reset.assert_called_once()


def test_only_completed_game_gets_new_color_before_next_epoch(tmp_path):
    env = _make_mock_katago_vecenv(alternate_players=True, terminate_at_step=2)
    loop = KataGoTrainingLoop(_config(tmp_path, 50), vecenv=env)
    sides = []
    original = katago_loop.split_merge_step

    def capture(**kwargs):
        sides.append(kwargs["learner_side"].copy())
        return original(**kwargs)

    with (
        patch.object(katago_loop, "split_merge_step", side_effect=capture),
        patch.object(
            katago_loop.np.random, "randint",
            side_effect=[
                np.array([0, 1], dtype=np.uint8),
                np.array([1], dtype=np.uint8),
                np.array([0, 0], dtype=np.uint8),
            ],
        ) as random_colors,
    ):
        loop.run(num_epochs=2, steps_per_epoch=2)

    assert [side.tolist() for side in sides] == [[0, 1], [0, 1], [1, 1], [1, 1]]
    assert random_colors.call_count == 2
    env.reset.assert_called_once()
