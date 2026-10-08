"""Training restart must preserve the checkpoint's learner and optimization state."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

from keisei.config import AppConfig, LeagueConfig
from keisei.db import read_training_state, update_training_progress
from keisei.training.checkpoint import save_checkpoint
from keisei.training.katago_loop import KataGoTrainingLoop
from tests.test_katago_loop import _make_config, _make_mock_katago_vecenv

pytestmark = pytest.mark.integration


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    base = _make_config(tmp_path)
    params = dict(base.training.algorithm_params)
    params.update(
        epochs_per_batch=1,
        batch_size=8,
        entropy_decay_epochs=20,
        rl_warmup={"epochs": 10, "entropy_bonus": 0.05},
        lr_schedule={"patience": 100},
    )
    return dataclasses.replace(
        base,
        training=dataclasses.replace(
            base.training, checkpoint_interval=1, algorithm_params=params,
        ),
        model=dataclasses.replace(
            base.model,
            params={
                "num_blocks": 1, "channels": 8, "se_reduction": 2,
                "global_pool_channels": 4, "policy_channels": 2,
                "value_fc_size": 8, "score_fc_size": 8, "obs_channels": 50,
            },
        ),
        league=LeagueConfig(epochs_per_seat=50, color_randomization=False),
    )


@pytest.fixture(autouse=True)
def cpu_threads():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


def _loop(config: AppConfig, *, resume_mode: str = "rl") -> KataGoTrainingLoop:
    return KataGoTrainingLoop(
        config, vecenv=_make_mock_katago_vecenv(), resume_mode=resume_mode,
    )


def _save_legacy_checkpoint(loop: KataGoTrainingLoop, epoch: int) -> Path:
    path = Path(loop.config.training.checkpoint_dir) / f"legacy_{epoch}.pt"
    save_checkpoint(
        path, loop._base_model, loop.ppo.optimizer, epoch, loop.global_step,
        architecture=loop.config.model.architecture, scheduler=loop.lr_scheduler,
    )
    update_training_progress(
        loop.db_path, epoch, loop.global_step, str(path),
        learner_entry_id=loop._learner_entry_id,
    )
    return path


def test_resume_preserves_pool_and_learner_identity(config: AppConfig):
    loop = _loop(config)
    with torch.no_grad():
        next(loop.model.parameters()).fill_(2.0)
    loop._rotate_seat(49)
    _save_legacy_checkpoint(loop, epoch=55)
    assert loop.store is not None
    entry_ids = {entry.id for entry in loop.store.list_entries()}
    learner_id = loop._learner_entry_id

    resumed = _loop(config)

    assert resumed.store is not None
    assert {entry.id for entry in resumed.store.list_entries()} == entry_ids
    assert resumed._learner_entry_id == learner_id
    assert read_training_state(loop.db_path)["learner_entry_id"] == learner_id
    assert next(resumed.model.parameters()).flatten()[0].item() == 2.0


def test_sl_bootstrap_contains_restored_weights(config: AppConfig):
    sl_loop = _loop(dataclasses.replace(config, league=None))
    with torch.no_grad():
        next(sl_loop.model.parameters()).fill_(2.0)
    _save_legacy_checkpoint(sl_loop, epoch=7)

    resumed = _loop(config, resume_mode="sl")

    assert resumed.store is not None
    entry = resumed.store.get_entry(resumed._learner_entry_id)
    assert entry is not None
    snapshot = resumed.store.load_opponent(entry, "cpu")
    assert next(snapshot.parameters()).flatten()[0].item() == 2.0
    assert resumed.epoch == 0
    assert resumed.ppo.warmup_epochs == 10


@pytest.mark.parametrize("legacy", [False, True])
def test_resume_preserves_seat_relative_entropy(config: AppConfig, legacy: bool):
    loop = _loop(config)
    loop._rotate_seat(49)
    loop.epoch = 55
    if legacy:
        _save_legacy_checkpoint(loop, epoch=55)
    else:
        loop.run(num_epochs=1, steps_per_epoch=2)
    expected = [loop.ppo.get_entropy_coeff(epoch) for epoch in (55, 59, 60, 65, 80)]

    resumed = _loop(config)

    assert resumed.ppo.warmup_epochs == 60
    assert [resumed.ppo.get_entropy_coeff(epoch) for epoch in (55, 59, 60, 65, 80)] == expected


def test_resume_uses_checkpoint_identity_when_db_has_later_rotation(config: AppConfig):
    loop = _loop(config)
    loop._rotate_seat(49)
    checkpoint_learner_id = loop._learner_entry_id
    loop.epoch = 55
    loop.run(num_epochs=1, steps_per_epoch=2)
    loop._rotate_seat(60)
    assert loop._learner_entry_id != checkpoint_learner_id

    resumed = _loop(config)

    assert resumed._learner_entry_id == checkpoint_learner_id
    assert read_training_state(loop.db_path)["learner_entry_id"] == checkpoint_learner_id


def test_failed_save_keeps_last_valid_checkpoint_pointer(config: AppConfig):
    loop = _loop(config)
    previous_path = _save_legacy_checkpoint(loop, epoch=1)
    loop.epoch = 2

    with patch("keisei.training.katago_loop.save_checkpoint", side_effect=OSError("disk full")):
        loop.run(num_epochs=1, steps_per_epoch=2)

    state = read_training_state(loop.db_path)
    assert state["checkpoint_path"] == str(previous_path)
    assert previous_path.exists()


def test_first_resumed_epoch_preserves_scheduler_history(config: AppConfig):
    loop = _loop(config)
    assert loop.lr_scheduler is not None
    loop.lr_scheduler.best = -1e6
    loop.lr_scheduler.num_bad_epochs = 5
    _save_legacy_checkpoint(loop, epoch=12)
    resumed = _loop(config)
    assert resumed.lr_scheduler is not None

    resumed.run(num_epochs=1, steps_per_epoch=2)

    assert resumed.lr_scheduler.best == -1e6
    assert resumed.lr_scheduler.num_bad_epochs == 6
