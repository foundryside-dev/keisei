"""Dynamic league learning must preserve both outcomes and behavior policies."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import torch
from torch import nn

from keisei.config import ConcurrencyConfig, DynamicConfig
from keisei.db import init_db
from keisei.db.tournament_queue import claim_next_pairings_batch, enqueue_pairings
from keisei.training.concurrent_matches import ConcurrentMatchPool
from keisei.training.dynamic_trainer import DynamicTrainer, MatchRollout
from keisei.training.match_utils import play_batch
from keisei.training.opponent_store import OpponentStore, Role
from keisei.training.tournament_runner import TournamentWorker


class SmallModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.policy = nn.Linear(1, 2)
        self.value = nn.Linear(1, 3)
        nn.init.zeros_(self.policy.weight)
        nn.init.zeros_(self.policy.bias)
        nn.init.zeros_(self.value.weight)
        nn.init.zeros_(self.value.bias)

    def forward(self, obs: torch.Tensor) -> SimpleNamespace:
        x = obs.reshape(len(obs), 1)
        return SimpleNamespace(policy_logits=self.policy(x), value_logits=self.value(x))


@pytest.fixture
def league(tmp_path: Path):
    db = str(tmp_path / 'league.db')
    init_db(db)
    store = OpponentStore(db, str(tmp_path / 'league'))
    with patch('keisei.training.opponent_store.build_model', side_effect=lambda *_: SmallModel()):
        a = store.add_entry(SmallModel(), 'small', {}, epoch=1, role=Role.DYNAMIC)
        b = store.add_entry(SmallModel(), 'small', {}, epoch=1, role=Role.RECENT_FIXED)
        yield store, a, b
    store.close()


def rollout() -> MatchRollout:
    return MatchRollout(
        observations=torch.ones(4, 1, 1), actions=torch.zeros(4, 1, dtype=torch.long),
        rewards=torch.tensor([[0.], [0.], [0.], [1.]]),
        dones=torch.tensor([[0.], [0.], [0.], [1.]]),
        legal_masks=torch.ones(4, 1, 2, dtype=torch.bool),
        perspective=torch.tensor([[0], [1], [0], [1]]),
    )


def trainer_for(store: OpponentStore) -> DynamicTrainer:
    return DynamicTrainer(store, DynamicConfig(update_every_matches=1, disable_on_error=False), 0.1)


def test_defeated_player_all_moves_receive_negative_targets(league):
    store, a, _ = league
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), side=0)
    _, _, rewards, valid, _ = trainer._prepare_batch(a.id, 'cpu')
    torch.testing.assert_close(rewards, torch.tensor([-1., -1.]))
    assert valid.bool().all()


def test_losing_policy_and_value_head_learn_from_opponents_terminal_move(league):
    store, a, _ = league
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), side=0)
    assert trainer.update(a, 'cpu')
    out = store.load_opponent(a)(torch.ones(1, 1))
    assert out.policy_logits.softmax(-1)[0, 0] < 0.5
    assert out.value_logits.softmax(-1)[0, 2] > 1 / 3


def test_truncation_and_unfinished_episodes_do_not_become_draw_targets(league):
    store, a, _ = league
    data = replace(rollout(), rewards=torch.zeros(4, 1), terminated=torch.zeros(4, 1))
    trainer = trainer_for(store)
    trainer.record_match(a.id, data, side=0)
    assert not trainer.update(a, 'cpu')
    assert store.get_entry(a.id).update_count == 0


def test_cache_refreshes_after_other_store_overwrites_checkpoint(league):
    store, a, _ = league
    old = store.load_opponent_cached(a, max_cached=2)
    with OpponentStore(store.db_path, str(store.league_dir)) as other:
        state = SmallModel().state_dict()
        state['policy.bias'][0] = 2.0
        other.save_weights(a.id, state)
    new = store.load_opponent_cached(a, max_cached=2)
    assert new is not old
    assert new.policy.bias[0] == 2.0


def test_nonfinite_update_cannot_overwrite_checkpoint(league):
    store, a, _ = league
    before = Path(a.checkpoint_path).read_bytes()
    trainer = trainer_for(store)
    data = rollout()
    data.observations[0, 0, 0] = float('inf')
    trainer.record_match(a.id, data, side=0)
    with pytest.raises((ValueError, RuntimeError), match='finite|NaN'):
        trainer.update(a, 'cpu')
    assert Path(a.checkpoint_path).read_bytes() == before


def test_dynamic_gradient_forwards_preserve_eval_behavior(league):
    store, a, _ = league
    model = SmallModel()
    states: list[bool] = []
    model.register_forward_pre_hook(lambda module, _: states.append(module.training))
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), side=1)
    with patch.object(store, 'load_opponent', return_value=model.eval()):
        assert trainer.update(a, 'cpu')
    assert states and not any(states)


def test_stale_behavior_revision_is_discarded(league):
    store, a, _ = league
    data = replace(rollout(), checkpoint_versions=('stale', None), log_probs=torch.full((4, 1), -0.693147))
    trainer = trainer_for(store)
    trainer.record_match(a.id, data, side=0)
    assert not trainer.update(a, 'cpu')
    assert store.get_entry(a.id).update_count == 0
    assert not trainer.should_update(a.id)


def test_two_dynamic_trainers_serialize_entry_writes(league):
    store, a, _ = league
    trainers = [trainer_for(store), trainer_for(store)]
    active = 0
    peak = 0
    guard = threading.Lock()
    def inner(*_):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return True
    for trainer in trainers:
        trainer._update_inner = inner
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert all(workers.map(lambda trainer: trainer.update(a, 'cpu'), trainers))
    assert peak == 1


class TwoPlyEnv:
    """Reuse output storage like the native engine; White wins on its move."""
    def __init__(self):
        self.obs = np.zeros((1, 1), dtype=np.float32)
        self.masks = np.ones((1, 2), dtype=bool)
        self.ply = 0

    def reset(self):
        self.ply = 0
        self.obs.fill(0)
        return SimpleNamespace(observations=self.obs, legal_masks=self.masks)

    def step(self, _actions):
        self.ply += 1
        self.obs.fill(self.ply)
        done = self.ply == 2
        return SimpleNamespace(
            observations=self.obs, legal_masks=self.masks,
            current_players=np.array([self.ply % 2], dtype=np.uint8),
            rewards=np.array([float(done)], dtype=np.float32),
            terminated=np.array([done]), truncated=np.array([False]),
        )


@pytest.mark.parametrize('concurrent', [False, True])
def test_collectors_preserve_behavior_log_probs_revisions_and_observations(league, concurrent):
    store, a, b = league
    model_a, model_b = store.load_opponent(a), store.load_opponent(b)
    env = TwoPlyEnv()
    if concurrent:
        pool = ConcurrentMatchPool(ConcurrencyConfig(parallel_matches=1, envs_per_match=1, total_envs=1))
        results, _ = pool.run_round(
            env, [(a, b)], load_fn=lambda entry: model_a if entry.id == a.id else model_b,
            release_fn=lambda *_: None, trainable_fn=lambda *_: True,
            games_per_match=1, max_ply=2,
        )
        data = results[0].rollout
    else:
        _, _, _, data = play_batch(
            env, model_a, model_b, device=torch.device('cpu'), num_envs=1,
            max_ply=2, collect_rollout=True,
        )
    assert data is not None
    assert data.observations[:, 0, 0].tolist() == [0., 1.]
    torch.testing.assert_close(data.log_probs, torch.full((2, 1), -0.693147))
    assert data.terminated[:, 0].tolist() == [False, True]
    assert data.checkpoint_versions == (store.checkpoint_version(a), store.checkpoint_version(b))


@pytest.mark.parametrize("both_dynamic", [False, True])
def test_sidecar_runs_real_dynamic_learning(league, both_dynamic):
    store, a, b = league
    if both_dynamic:
        store.update_role(b.id, Role.DYNAMIC, "test both trainable sides")
        b = store.get_entry(b.id)
    config = ConcurrencyConfig(parallel_matches=1, envs_per_match=1, total_envs=1)
    worker = TournamentWorker(
        db_path=store.db_path, league_dir=str(store.league_dir), worker_id='dynamic-test',
        device='cpu', concurrency=config, games_per_match=1, max_ply=2,
        dynamic_config=DynamicConfig(update_every_matches=1, disable_on_error=False), learner_lr=.1,
    )
    enqueue_pairings(store.db_path, round_id=1, pairings=[(a.id, b.id, 1)], epoch=1)
    claims = claim_next_pairings_batch(store.db_path, worker_id='dynamic-test', limit=1, current_epoch=1, max_staleness_epochs=50)
    worker._play_batch(TwoPlyEnv(), claims)
    assert store.get_entry(a.id).update_count == 1
    learned = store.load_opponent(a)(torch.ones(1, 1)).value_logits.softmax(-1)[0, 2]
    assert learned > 1 / 3
    if both_dynamic:
        assert store.get_entry(b.id).update_count == 1
        assert store.load_opponent(b)(torch.ones(1, 1)).value_logits.softmax(-1)[0, 0] > 1 / 3
    worker.store.close()


def test_disabled_entry_does_not_train(league):
    store, a, _ = league
    with store.transaction():
        store._conn.execute('UPDATE league_entries SET training_enabled=0 WHERE id=?', (a.id,))
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    assert not trainer.update(a, 'cpu')
    assert store.get_entry(a.id).update_count == 0


def test_entry_retired_while_waiting_for_writer_lock_does_not_train(league):
    import fcntl
    store, a, _ = league
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    lock_path = Path(a.checkpoint_path).with_suffix('.training.lock')
    started = threading.Event()
    def update():
        started.set()
        return trainer.update(a, 'cpu')
    with lock_path.open('a') as file_lock, ThreadPoolExecutor(max_workers=1) as workers:
        fcntl.flock(file_lock.fileno(), fcntl.LOCK_EX)
        task = workers.submit(update)
        assert started.wait(1)
        store.retire_entry(a.id, 'retired during queued update')
        fcntl.flock(file_lock.fileno(), fcntl.LOCK_UN)
        assert not task.result(timeout=5)
    assert store.get_entry(a.id).update_count == 0


def test_stale_pruning_preserves_fresh_matches_until_threshold(league):
    store, a, _ = league
    trainer = DynamicTrainer(store, DynamicConfig(update_every_matches=4, disable_on_error=False), .1)
    stale = replace(rollout(), checkpoint_versions=('stale', None))
    for _ in range(3):
        trainer.record_match(a.id, stale, 0)
    fresh = replace(rollout(), checkpoint_versions=(store.checkpoint_version(a), None),
                    log_probs=torch.full((4, 1), -.693147))
    trainer.record_match(a.id, fresh, 0)
    assert not trainer.update(a, 'cpu')
    assert len(trainer._rollout_buffers[a.id]) == 1
    assert not trainer.should_update(a.id)
    for _ in range(3):
        trainer.record_match(a.id, fresh, 0)
    assert trainer.update(a, 'cpu')


def test_optimizer_and_weights_publish_together_on_every_update(league):
    store, a, _ = league
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    assert trainer.update(a, 'cpu')
    state = store.load_optimizer(a.id)
    assert state is not None
    steps = [value['step'].item() for value in state['state'].values()]
    assert steps and all(step == 2 for step in steps)
    another_worker = trainer_for(store)
    another_worker.record_match(a.id, rollout(), 0)
    assert another_worker.update(a, 'cpu')
    state = store.load_optimizer(a.id)
    assert all(value['step'].item() == 4 for value in state['state'].values())


def test_optimizer_publication_failure_rolls_back_weights(league):
    store, a, _ = league
    before = Path(a.checkpoint_path).read_bytes()
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    with patch.object(store, 'save_optimizer', side_effect=RuntimeError('optimizer write failed')):
        with pytest.raises(RuntimeError, match='optimizer write failed'):
            trainer.update(a, 'cpu')
    assert Path(a.checkpoint_path).read_bytes() == before
    assert store.get_entry(a.id).update_count == 0


def test_combining_independently_reset_batches_never_joins_episodes(league):
    from keisei.training.match_utils import _combine_rollouts
    store, a, _ = league
    first = rollout()
    first.dones.zero_()
    first.rewards.zero_()
    first.observations.fill_(11.)
    second = rollout()
    second.observations.fill_(22.)
    trainer = trainer_for(store)
    trainer.record_match(a.id, _combine_rollouts([first, second]), 0)
    observations, _, rewards, _, _ = trainer._prepare_batch(a.id, 'cpu')
    assert observations.flatten().tolist() == [22., 22.]
    assert rewards.tolist() == [-1., -1.]


def test_failed_cpu_update_preserves_committed_optimizer_momentum(league):
    from copy import deepcopy

    from keisei.training.katago_ppo import ppo_clip_loss
    store, a, _ = league
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    assert trainer.update(a, 'cpu')
    before = deepcopy(trainer._optimizers[a.id].state_dict())
    calls = 0
    def fail_second_epoch(*args, **kwargs):
        nonlocal calls
        calls += 1
        loss = ppo_clip_loss(*args, **kwargs)
        return loss if calls == 1 else loss * float('nan')
    trainer.record_match(a.id, rollout(), 0)
    with patch('keisei.training.dynamic_trainer.ppo_clip_loss', side_effect=fail_second_epoch):
        with pytest.raises(RuntimeError, match='finite'):
            trainer.update(a, 'cpu')
    after = trainer._optimizers[a.id].state_dict()
    for index, state in before['state'].items():
        for name, value in state.items():
            torch.testing.assert_close(after['state'][index][name], value)


def test_retirement_immediately_before_publication_blocks_checkpoint_write(league):
    from contextlib import contextmanager
    store, a, _ = league
    before = Path(a.checkpoint_path).read_bytes()
    trainer = trainer_for(store)
    trainer.record_match(a.id, rollout(), 0)
    original = store.transaction
    retired = False
    with OpponentStore(store.db_path, str(store.league_dir)) as other:
        @contextmanager
        def racing_transaction():
            nonlocal retired
            if not retired:
                retired = True
                other.retire_entry(a.id, 'retirement won publication race')
            with original():
                yield
        with patch.object(store, 'transaction', racing_transaction):
            assert not trainer.update(a, 'cpu')
    assert Path(a.checkpoint_path).read_bytes() == before
    assert store.get_entry(a.id).update_count == 0


def test_sidecar_cli_forwards_dynamic_config_and_learner_learning_rate():
    from keisei.config import LeagueConfig
    from keisei.training.tournament_runner import main
    dynamic = DynamicConfig(update_every_matches=7, max_updates_per_minute=3)
    config = SimpleNamespace(
        league=LeagueConfig(dynamic=dynamic),
        training=SimpleNamespace(max_ply=20, algorithm_params={'learning_rate': .003}),
    )
    with patch('keisei.training.tournament_runner.load_config', return_value=config), \
         patch('keisei.training.tournament_runner.signal.signal'), \
         patch('keisei.training.tournament_runner.TournamentWorker') as worker:
        assert main(['--config', 'unused.toml', '--db-path', 'unused.db',
                     '--league-dir', 'unused', '--worker-id', 'worker-test', '--device', 'cpu']) == 0
    arguments = worker.call_args.kwargs
    assert arguments['dynamic_config'] is dynamic
    assert arguments['dynamic_config'].update_every_matches == 7
    assert arguments['dynamic_config'].max_updates_per_minute == 3
    assert arguments['learner_lr'] == .003


def test_dynamic_ppo_uses_recorded_behavior_log_probabilities(league):
    from keisei.training.katago_ppo import ppo_clip_loss
    store, a, _ = league
    data = replace(rollout(), log_probs=torch.full((4, 1), -.3),
                   checkpoint_versions=(store.checkpoint_version(a), None))
    trainer = trainer_for(store)
    trainer.record_match(a.id, data, 0)
    captured = []
    def capture(new, old, *args, **kwargs):
        captured.append(old.detach().clone())
        return ppo_clip_loss(new, old, *args, **kwargs)
    with patch('keisei.training.dynamic_trainer.ppo_clip_loss', side_effect=capture):
        assert trainer.update(a, 'cpu')
    assert captured
    assert all(torch.equal(old, torch.full_like(old, -.3)) for old in captured)
