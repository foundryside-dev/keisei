# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **WebUI "About" tab** — progressive-disclosure explainer of the system at five
  levels (Big Idea → Learning Loop → Inside the Demo → Algorithmic →
  Research View) with sticky level selector, right-rail TOC, SVG architecture
  diagrams, and print stylesheet. Selected level persists in localStorage.
- **Background lofi audio toggle** in the tab bar — opt-in, persisted, served
  via a new `/audio` static mount on the FastAPI server (mounted from the repo
  root so the ~700 MB asset stays out of the bundled `static/` dir; uses HTTP
  Range so streaming is on demand). Vite dev proxy forwards `/audio` to the
  backend.
- **Tournament-queue saturation logging** in `KataGoTrainingLoop` — warns when
  the dispatcher queue hits ≥90% capacity and again when fully saturated, so a
  worker that has fallen behind dispatch cadence surfaces in logs instead of
  silently dropping work.

### Fixed
- **Engine undo and loaded positions** — undo restores the prior game result so
  adjudicated branches cannot contaminate later moves. Playable SFEN loading
  rejects double pawns and unpromoted pieces stranded on forbidden ranks.
- **Spectator promotion notation** — already-promoted pawns, lances, and knights
  no longer receive a second promotion marker when moving onto their last ranks.
- **PPO critic supervision** — completed games train W/D/L predictions for all
  recorded positions, including earlier losing-side moves and games spanning
  rollout boundaries. Delayed positions are used only for critic supervision.
- **PPO epoch boundaries** — finish outstanding opponent responses before an
  optimizer update, preserving terminal rewards and truncation bootstraps.
  Masked vector stepping pauses unrelated games during that completion step.
- **League dashboard records** — lifetime totals and W/L/D include all results;
  learner summaries use its latest ten tournament epochs. Sorting preserves
  ranking and champion identity on a shared composite Elo scale. Historical
  benchmarks are accessible, configured capacities are respected, and narrow
  screens keep navigation and league content reachable.
- **Spectator controls and results** — match requests and speed/cancel commands
  validate identities, report correlated acknowledgements and errors, and enforce
  queue limits atomically. Finished boards and results remain visible through idle
  periods and reconnects. Queue and league metadata changes are pushed promptly;
  completed-round telemetry is labelled with its timestamp rather than shown as live.
- **Showcase inference and liveness** — use real KataGo check/repetition features,
  refresh replaced model checkpoints, reject non-finite model output, retain
  decisive engine winners on the final ply, publish heartbeats during games, and
  recover a dead runner even when its last heartbeat is recent. Exclusive process
  ownership prevents duplicate runners from corrupting game and heartbeat state.
- **Engine input and terminal safety** — validate SFEN syntax, hand bounds,
  playable kings/material and turn consistency before simulation. Loaded terminal
  positions are adjudicated immediately; checked kings cannot trigger impasse.
  Safe move-list access checks bounds in release builds, invalid backward knight
  encodings return errors, and native ply limits cannot overflow metadata.
- **Native package distribution** — wheels include the Python wrapper, type stubs
  and typing marker, including when rebuilt from a source distribution. CI tests
  normal package installs and runs the frontend regression suite.
- **PPO trajectory and likelihood correctness** — alternating self-play traces
  use mover-relative signs; truncation stops traces while retaining terminal-board
  bootstrap values. Dense and partial rollouts preserve environment identity across
  buffer reuse. Learner colors persist until each game ends, including across
  epochs and seat rotations. Collection and updates share float32 legal-action distributions and
  evaluation-mode normalization, including compiled and mixed-precision forwards.
- **Training restart state** — restore the learner before initializing the league,
  preserve seat-relative entropy warmup and scheduler history, and retain the last
  valid checkpoint pointer when a save fails.
- **Dynamic opponent learning** — sidecar tournaments now train eligible entries
  from both players' completed-game outcomes and recorded behavior probabilities.
  Workers serialize updates, discard stale trajectories, publish matching weights
  and optimizer state transactionally, and refresh retained opponent checkpoints.
  Sidecar results also maintain role-specific ratings with serialized rating updates.
- **Game adjudication** — perpetual check requires uninterrupted checking throughout
  the repetition interval; genuine endings on the final allowed ply retain their
  terminal reward instead of becoming time-limit draws.
- **PPO numerical safeguards** — disabled auxiliary heads and ignored value labels
  cannot inject NaN gradients through the shared trunk. Non-finite active losses or
  gradients stop before an optimizer step, with unused-head support for DDP.
  Masked entropy excludes illegal log probabilities before loss scaling, avoiding
  overflow that could otherwise skip every CUDA update.
- **`play_match()` overshoot when `num_envs > games_target`** — the first/final
  partial batch counted every completed lane, so e.g. `games_target=1` with
  `num_envs=4` returned 4 games. `play_batch()` now takes an `active_envs`
  cap, masks completion bookkeeping and rollout-perspective rows for surplus
  lanes, and `play_match()` returns exactly `games_target` games. Closes
  `keisei-285eceba8b`.
- **WebUI league events leaked across training runs** — first-load logic now
  fingerprints `(id, display_name)` pairs and only clears persisted events
  when no fingerprint overlaps the current pool (DB wipe, league reset,
  switched config). Mid-run page refreshes preserve the event log instead of
  discarding it on every reload.
- **WebUI skip-nav target was hard-coded for the old two-tab layout.** It now
  resolves to `#${activeTab}-main`, and `LeagueView` / `ShowcaseView` /
  `AboutView` each expose a programmatically-focusable `<main>` with
  `tabindex="-1"` and `aria-labelledby` pointing at the corresponding tab
  button.

### Changed
- Dynamic optimizer state is saved with every weight update; the obsolete
  `checkpoint_flush_every` setting is removed. Dynamic update thresholds must fit
  the retained rollout buffer. Multi-head DDP requires `find_unused_parameters = true`
  (now the default) because a minibatch can contain no value labels.
- **WebUI Knight legend** uses jump glyphs (⇖ / ⇗) in row 0 of a uniform 3×3
  grid instead of an extra row above the grid. Every piece's legend is now
  the same physical height, simplifying layout. `KNIGHT_EXTRA` and the
  `extra` prop on `MoveDots` are removed.

## [1.0.0] - 2026-05-02

First stable release. Keisei is a Deep Reinforcement Learning system for Shogi
built on a Rust game engine and a Python/PyTorch training harness, with a
KataGo-inspired SE-ResNet as the primary network, opponent league self-play,
supervised-learning warmup, and a live spectator WebUI.

### Added

#### Rust Engine (`shogi-engine/`)
- **shogi-core** crate — full Shogi implementation: board representation, legal
  move generation, rule enforcement (check, checkmate, repetition, impasse),
  SFEN parsing/serialization, Zobrist hashing, `material_balance()`, and
  per-piece value lookup.
- **shogi-gym** crate — RL environment layer: `VecEnv` vectorized environment,
  46-channel and 50-channel observation encoders (KataGo mode adds repetition
  count planes 1x/2x/3x/4+ and a check indicator), flat 13,527-action and
  spatial 11,259-action mappers (81 squares x 139 move types), per-step
  `material_balance` buffer, and step/reset API exposed to Python via PyO3.
- Spectator data layer — `get_spectator_data()`, `SpectatorEnv.from_sfen()`,
  `get_sfen()` / `get_sfens()`, episode-length statistics, and shared
  `build_spectator_dict()` helper for live game visualization.

#### Neural Network Architectures
- **SE-ResNet** (primary) — KataGo-style trunk with `GlobalPoolBiasBlock`
  (global pooling bias projected through a bottleneck FC, plus
  Squeeze-and-Excitation with scale+shift). Default 40 blocks x 256 channels.
- **ResNet**, **MLP**, **Transformer** — baseline / ablation architectures with
  scalar value heads.
- Three-head output for SE-ResNet: spatial policy `(B, 9, 9, 139)` with
  legal-mask softmax, W/D/L value classification `(B, 3)`, and material score
  prediction `(B, 1)`.
- `KataGoBaseModel` ABC, `KataGoOutput` dataclass, model registry with
  contract type and `obs_channels` metadata.

#### Training
- **PPO** with rollout buffer, Generalized Advantage Estimation (GAE), clipped
  surrogate objective, mini-batch updates, and global gradient clipping.
- **KataGo-PPO** — multi-head loss (policy + W/D/L cross-entropy + score MSE +
  entropy bonus) with `KataGoRolloutBuffer` storing `value_categories` and
  `score_targets`, plus NaN/unnormalized guards.
- **Per-step material balance** drives the score head (replaces the original
  reward/76 scheme) for a dense, per-position regression target.
- **Value adapter pattern** (`ScalarValueAdapter`, `MultiHeadValueAdapter`) so
  the training loop is model-agnostic across scalar and multi-head contracts.
- **Supervised learning warmup** — `CSAParser` for Floodgate game records
  (Shift-JIS detection, PI initial position, P+/P- placement),
  memory-mapped `SLDataset` binary shards, `SLTrainer`, `keisei-prepare-sl`
  CLI, and `ReduceLROnPlateau` scheduler in the training loop.
- **RL warmup** with elevated entropy coefficient to soften overconfident SL
  policies.
- **Mixed precision (AMP / bf16)** — wired through PPO update, SL trainer, and
  `select_actions` rollout inference; GradScaler state persisted in
  checkpoints.
- **`torch.compile`** enabled across configs for fused kernel execution.
- **DDP** support and per-epoch timing breakdowns to diagnose rollout
  degradation.
- **Checkpointing** — model weights, optimizer state, GradScaler, RNG state,
  scheduler state, architecture metadata, and `learner_entry_id` for safe
  resume.

#### Opponent League and Tournament
- **`OpponentPool`** with SQLite-backed model storage, Elo tracking, tiered
  pool with `max_active_entries` cap, role-grouped leaderboard
  (Frontier / Dynamic / Demonstrator), and LRU model cache sized to the full
  pool.
- **`OpponentSampler`** — weighted opponent selection with Elo-floor and
  ratio controls.
- **Split-merge step** for learner vs. opponent forward passes; vectorized
  per-env partition (argsort+split) and GPU padded GAE for the split-merge
  hot path.
- **Promotion / demotion** — `PriorityScorer`, frontier-vs-dynamic Elo
  tracking, weakest-dynamic eviction, and bootstrap-from-flat-pool logic.
- **Tournament sidecar** — extracted into a separate worker subprocess with
  `ConcurrentMatchPool`, batch inference across slots by model identity,
  batch-claim DB op with in-transaction staleness sweep, `min_coverage_ratio`
  weighted-round generation, server-side head-to-head pre-aggregation, and
  pairing-queue index on `(status, enqueued_epoch)`.
- **`DemonstratorRunner`** for inference-only exhibition matches and
  `keisei-evaluate` CLI for head-to-head checkpoint comparison (with GPU
  device support).

#### Showcase Mode
- Model-vs-model showcase tab — sidecar runner with game loop, heartbeat, and
  auto-showcase; CPU-only inference with model cache; DB tables (schema v3)
  for queue, games, moves, and heartbeat; WebSocket polling, client commands,
  and init support; Svelte UI with board, commentary panel, controls, and
  queue.
- Spatial action mapper used in `SpectatorEnv` so showcase replays match the
  trained models' action space.

#### WebUI (Svelte)
- League view restructured with always-visible matchup matrix, contextual
  sparkline, role-grouped leaderboard, role tier badges, protection badges,
  rounds/games stats banner, and 2x2 grid layout to prevent jerk on entry
  selection.
- `EntryDetail` component with Last Round, Overall Record, Role Stats, Elo
  trend chart, and improved typography.
- `HistoricalLibrary` component with slot table and gauntlet results.
- `RecentMatches` with Elo ratings and upset indicators.
- Showcase tab with board, commentary, controls, and queue.
- Metrics chart with dual-axis support and P/V ratio calculation.
- Transition count summary and batch-collapse in the event log; localStorage
  persistence across reloads.
- Opponent style profiling and card data system.
- Accessibility and contrast fixes from design review.

#### Database
- SQLite (WAL mode) for training metrics, game snapshots, training state, and
  spectator data.
- Schema versioning with v2 (league tables, `game_type` column) and v3
  (showcase tables); `learner_entry_id` column on `training_state` with
  migration.
- Batched end-of-epoch writes via a single connection + transaction;
  thread-local SQLite connections + WAL checkpoint to prevent epoch
  degradation.
- `read_elo_history` with `max_epochs` support and supporting index.
- `head_to_head` backfill on schema upgrade with transaction handling and
  self-play row skipping.

#### Configuration and CLI
- TOML config loading with frozen dataclass validation (`AppConfig`,
  `TrainingConfig`, `ModelConfig`, `DisplayConfig`, `LeagueConfig`,
  `DemonstratorConfig`).
- Six provided configs: `keisei-katago.toml` (primary), `keisei-ddp.toml`,
  `keisei-500k.toml`, `keisei-h200.toml`, `keisei-league.toml`,
  `keisei-500k-league.toml`.
- Entry points: `keisei-train`, `keisei-evaluate`, `keisei-serve`,
  `keisei-prepare-sl`.

#### Profiling and Diagnostics
- Component-level hot-path profiler with loss-component and memory analysis.
- `compute_value_metrics` for W/D/L prediction monitoring (degeneracy
  detection).
- Tournament monitoring instrumentation.

#### Project Infrastructure
- `CONTRIBUTING.md`, `SECURITY.md`, `.editorconfig`, PR template.
- GitHub Actions CI workflow (Python 3.12/3.13 + Rust).
- `py.typed` marker for PEP 561 compliance.
- `pyproject.toml` with authors, URLs, classifiers, keywords.
- README with badges, architecture detail, prior-art attribution
  (KataGo, AlphaZero), and collapsible sections.

### Changed
- **Rust replaces pure-Python engine.** All game logic, move generation, and
  observation encoding live in Rust; the Python harness consumes them via
  PyO3. The original pure-Python engine was removed.
- **Model registry** grew from one to four architectures; observation
  encoding from a single 46-channel format to 46/50-channel modes selected
  by model contract; action space from flat 13,527 to flat-or-spatial.
- **Training loop** unified — old `TrainingLoop` and `PPOAlgorithm` replaced
  by the league-aware loop wiring SE-ResNet + KataGoPPO + VecEnv +
  OpponentPool + split-merge.
- **Rollout cost** decoupled from opponent pool size; per-model overhead
  hoisted out of the rollout hot loop; pre-allocated contiguous rollout
  buffer; CPU-first buffer storage with overlapped GPU transfer.
- **Promotion logic** uses `elo_frontier` instead of generic `elo_rating`;
  dynamic-pool eviction uses `elo_dynamic`.
- Test suite grew from 74 Python / 188 Rust tests at 0.1.0 to **674 Python
  tests / 363 Rust tests** at 1.0.0, including AMP integration, checkpoint
  round-trip, GAE padded edge cases, SL trainer multi-epoch, OpponentPool /
  OpponentSampler edge cases, seat rotation, LR scheduler boundaries,
  WebSocket resilience, and many risk-based gap closures.
- `ruff` line-length raised from 100 to 140.

### Fixed
- **Score head:** per-step material balance replaces reward/76 (denser, more
  accurate signal); NaN sentinel removed from score loss.
- **PPO correctness:** entropy NaN from `0 * -inf` in masked softmax;
  BatchNorm train/eval mode toggling in action selection; old_log_probs
  computed in eval mode; AMP device type for non-CUDA devices.
- **Per-env GAE** correctness in split-merge mode; reindexed `next_values`
  for GPU padded GAE.
- **Knight decoder perspective bug** in shogi-gym; white knight decode
  produced wrong target square.
- **Optimizer state tensors** not moved to model device after checkpoint
  load.
- **Concurrent matches:** zero-legal guard `break`→`continue` and rollout
  alignment; LRU-cached models no longer moved to CPU on release;
  exception-safe cleanup.
- **CSA parser:** PI initial-position and P+/P- placement lines now parsed.
- **Showcase:** spatial action mapper in `SpectatorEnv` to match trained
  models; sidecar interop threads.
- **Tournament:** results recorded for entries retired mid-round; broad
  `except` no longer sends entire batch to terminal failed status (RFC for
  retry/requeue tracked); Elo reload from DB before recording batch results;
  use `PriorityScorer.score()` not `pair_priority()`; `--config` wired into
  `run.sh` tournament worker.
- **Database:** WAL checkpointing prevents epoch degradation; `head_to_head`
  INSERT guard for self-play matches; schema migrations for new columns.
- **WebUI:** stale league event log cleared on DB wipe; ELO display unified
  between stats banner and league table; localStorage persistence for league
  diffs; flaky WebSocket tests stabilized via `ws_connect` fixture.
- **Defensive bugs:** IPv6 host parsing, NaN softmax, glob case-sensitivity,
  threshold bypass, shutdown delay, GPU leak, device pinning, param
  validation, file ordering, rollback handling, weighted_sample budget,
  unknown config keys, DB migration, GradScaler guard, per-side feature
  tracking.
- **`torch._dynamo.explain`** API call updated for PyTorch 2.11.

### Removed
- Pure-Python Shogi engine and its test suite.
- Original scalar-only `TrainingLoop` and `PPOAlgorithm` classes.
- `keisei.toml` config — the basic-PPO algorithm is no longer supported;
  `katago_ppo` is the only training algorithm.
- Stale docs, plans, and specs from the pre-Rust era.
- NaN masking from score loss (per-step material gives a dense signal at
  every position).
- Noto Serif Google Font import in WebUI (~30KB savings).

[Unreleased]: https://github.com/tachyon-beep/keisei/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/tachyon-beep/keisei/releases/tag/v1.0.0
