"""A retained league opponent must refresh after an external weight update."""
from __future__ import annotations

import dataclasses

import pytest
import torch

from keisei.config import LeagueConfig
from keisei.training.katago_loop import KataGoTrainingLoop
from tests.test_katago_loop import _make_config, _make_mock_katago_vecenv


def test_retained_cohort_refreshes_weights_between_epochs(tmp_path, monkeypatch):
    base = _make_config(tmp_path)
    config = dataclasses.replace(
        base, league=LeagueConfig(color_randomization=False, epochs_per_seat=50),
        training=dataclasses.replace(base.training, algorithm_params={
            **base.training.algorithm_params, 'epochs_per_batch': 1,
        }),
    )
    loop = KataGoTrainingLoop(config, vecenv=_make_mock_katago_vecenv())
    opponent = loop.tiered_pool.snapshot_learner(
        loop._base_model, config.model.architecture, dict(config.model.params), epoch=0,
    )
    original = loop.ppo.update
    calls = 0

    def update(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        if calls == 0:
            replacement = loop.store.load_opponent(opponent)
            with torch.no_grad():
                replacement.score_fc2.bias.fill_(0.42)
            loop.store.save_weights(opponent.id, replacement.state_dict())
        calls += 1
        return result

    monkeypatch.setattr(loop.ppo, 'update', update)
    loop.run(num_epochs=2, steps_per_epoch=2)
    assert calls == 2
    assert loop._opponent_models[opponent.id].score_fc2.bias.item() == pytest.approx(0.42)
