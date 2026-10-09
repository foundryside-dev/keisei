# Spectator UX implementation evidence

2026-10-10, Australia/Canberra. Scope: all seven findings in the [reviewed execution plan](../../plans/2026-10-10-web-ux-remediation.md). Filigree milestone: `keisei-de3922e0d9`.

Implementation and browser checks passed. Astra's independent source review concluded **ready for integration**, with no outstanding material findings. Real screen-reader validation is **Unable to test**: neither this environment nor the user has one. The user explicitly accepted this delivery disposition; follow-up `keisei-ebe3c4bef2` remains open. This report does not certify screen-reader usability or production acceptance.

## Delivered behavior

| Package | Result |
|---|---|
| UX01 | Training prioritizes the selected board, exposes all loaded lanes, retains completed games, and announces deterministic fallback/replacement. Metrics and detailed player/run information open on demand. |
| UX02 | Watch match uses container and available-height sizing; narrow/short layouts use reachable document flow. Live, paused, replay and finished states are explicit. |
| UX03 | Replay keys are scoped to the viewer and cooperate with native buttons, disclosures and move cells. Pausing at the tail pins immediately; stepping back clamps at the first stored position. |
| UX04 | Versioned estimates identify the pre-move position and player. Scalar and draw-aware WDL outcome scores convert once to Black's perspective. Invalid/legacy estimates are unavailable or graph gaps. |
| UX05 | League offers unique player-perspective matchup records, full distinguishable names, complete-epoch pagination beyond the live 50-epoch window, retry and preserved loaded history. |
| UX06 | Full boards expose an English text position, hands, promotion and side to move. Announcements are opt-in. Entry Close/Escape restores the originating row or a meaningful heading fallback. |
| UX07 | Compact disclosures, Watch match naming and root-query URLs preserve entity/ply identity through reload, Back/Forward and sharing. Archived state is isolated from the live feed. |

## Independent Astra review

The requested `gpt-6-astra` reviewer inspected source and tests read-only. Five findings were corrected and rechecked:

1. Move selection scrolls only its own log container; live updates cannot scroll the document.
2. Replay shortcuts ignore native `summary` controls and other interactive targets.
3. Backward stepping clamps at the first position rather than entering the live-follow sentinel.
4. Per-ply scorecard updates no longer create always-on live announcements.
5. Compact player disclosures preserve architecture/topology discovery and visible tier/rating identity.

Final verdict: **ready for integration; no outstanding material findings against UX01–UX07**. Astra verified source/test consistency and `git diff --check`; it did not independently run the parent agent's test suite or browser matrix. Parent and implementation agents supplied the runtime evidence below.

## Automated checks

| Check | Result |
|---|---|
| `cd webui && npm test` | 46 files, **444 tests passed**, including final target-size edits |
| `cd webui && npm run build` | Production build passed |
| `.venv/bin/python -m pytest tests/test_showcase_inference.py tests/test_showcase_runner.py tests/test_showcase_db.py tests/test_server_showcase.py tests/test_server_gauntlet_history.py tests/test_server_showcase_history.py -q` | **72 passed** |
| `.venv/bin/python -m ruff check .` | Passed |
| `.venv/bin/python -m mypy keisei/` | Passed, 68 source files; unused-config-section note only |
| `git diff --check` | Passed |

Python API tests ran with sandbox escalation because this environment denied socket-pair creation and stalled AnyIO/TestClient inside the restricted sandbox; a minimal independent FastAPI case reproduced the environment limitation. No test assertions were disabled. Vite emits an existing `optimizeDeps.esbuildOptions` deprecation warning; compilation and tests succeed.

Tests cover additive/idempotent schema upgrade, legacy rows, scalar/WDL orientation, invalid data, ordered/bounded match retrieval, complete-epoch pagination, stale-response rejection, keyboard scope, accessible text positions and navigation/focus behavior. No training experiment or Rust source change was required.

## Playwright visual and interaction evidence

The built UI was served by the real FastAPI application against a disposable SQLite database, with actual WebSocket polling and read-only APIs. The committed [fixture](../../../scripts/ux_acceptance_fixture.py) seeds 32 lanes, 20 active league entries plus a retired entry, long/duplicate names, 51 evaluation epochs with five slots each, saved/legacy/live matches, draws, promoted pieces and legal drops. It uses the engine for legal positions and production heatmap construction. It does not open the configured training database.

```sh
cd webui && npm run build
cd ..
.venv/bin/python -m scripts.ux_acceptance_fixture --port 8765
# The process prints its temporary DB path; mutations target only that path.
.venv/bin/python -m scripts.ux_acceptance_fixture --db /tmp/PRINTED/fixture.sqlite --action append-move
```

The acceptance run used `http://127.0.0.1:8765`; a separate disposable server on 8766 exercised disconnect/reconnect and empty states. Browser scripts and structured results are saved in [evidence](evidence/). These are CLI review scripts, not a new application test framework. URLs, temporary paths and match IDs describe this run and should be adapted when reproducing.

### Layout matrix

[Structured measurements](evidence/viewport-matrix.json) cover Training, League and Watch match at every size below: **21 view/size combinations**, with no document-level horizontal overflow.

| CSS viewport | Observed result |
|---|---|
| 1920×1080 | Desktop viewer and secondary content reachable |
| 1440×900 | Entire Training board/trays and Watch board/trays/replay controls fit |
| 1280×800 | Entire Training board/trays and Watch board/trays/replay controls fit |
| 768×1024 | Complete width-fitting boards in document flow |
| 390×844 | Training first board row and League first leaderboard row visible; complete content reachable |
| 320×568 | Reflow without horizontal document scrolling; all board ranks and controls reachable |
| 844×390 | Short-height flow without clipped upper ranks |

At 1440×900 Training's board spans y=260–836 and its lower tray ends at 882; Watch's board spans y=338–762, lower tray ends at 808, and pause control ends at 900. At 1280×800 corresponding lower-tray/control bounds are 782 and 800. Expanded disclosures remain in normal flow.

Both themes were checked at 1440×900 and 390×844 across all three views. All visible enabled buttons in these **12 combinations** measured at least 44×44 CSS px ([results](evidence/final-capture.json)). Watch match also passed 200% text enlargement in both sizes/themes with 81 squares and no horizontal document overflow; reduced-motion transitions measured 0.00001 seconds ([results](evidence/contrast-zoom.json)). Text enlargement was applied to computed font sizes in the browser; 320 CSS px reflow was checked separately.

### Task and state checks

- **Choose and inspect Training:** all 32 lanes listed. A draw retains the selected lane and its final move; same-lane replacement resets to ply zero and announces the new game. Actual reconnect after removing the selected lane chooses the lowest remaining active lane and announces the fallback.
- **Watch/pause/scrub/resume:** native Space activates Heatmap and New match once; a native disclosure opens without pausing. Space on a move produces one URL replacement. Pause at ply 12 immediately says Paused; appending actual ply 13 leaves the board and document scroll unchanged. Explicit resume follows. Previous/Shift+Left clamp at the first stored position.
- **Saved-match sharing:** copied links preserve the displayed match/actual ply and unrelated query/hash values without changing following mode. A fresh browser context and reload restore the same position. Scrubbing replaces history; tab navigation pushes; Back/Forward restores the saved position. About anchors and tablist Home/arrows work. New live match 4 does not replace explicit match 3/ply 13; Watch latest match explicitly follows match 4.
- **Archive and unavailable data:** archived speed controls are disabled. Legacy and malformed evaluation are unavailable. Out-of-range ply shows a clamp explanation; missing match/entry and retired entry have useful recovery states. History API response ceilings and invalid IDs are tested.
- **League investigation:** duplicate long names show stable identity; a selected-player filter has the correct perspective. Actual API paging loaded all 51 epochs/255 rows, including data older than the live window. A new live epoch produced 52 unique epochs/260 rows with all five slots, no lost older rows, and zero scroll-position change. An injected history 503 retains existing rows; Retry loads the next page without duplicates.
- **Focus:** Close and Escape return to the originating row; if that row disappears, the leaderboard heading receives focus with status feedback. Direct URL/Back entry opening has no originating row and correctly uses the heading fallback.
- **Empty/offline/loading/commands:** disconnect retains the board with a reconnect alert; zero lanes show a clear empty state and connection action. Offline sidecar retains saved replay with an actionable alert. Held/aborted saved-match requests show loading/error without an unrelated board; Retry recovers. Actual New match submission renders pending feedback followed by the real server acknowledgement. Command rejection feedback is additionally covered by component tests.

Real browser native activation, geometry, fresh-context sharing and asynchronous feed mutation complement render/unit tests. Synthetic key events alone were not treated as proof of native activation. Console failures from deliberate 503/disconnect injection are expected; they are distinguished from product errors.

### Measured contrast

Values use resolved CSS colors and ancestor-composited backgrounds after theme transitions settle. Ratios are identical at the measured desktop/phone sizes. This is evidence for these pairs, not a theme-wide WCAG certification.

| Pair | Dark foreground/background; ratio | Light foreground/background; ratio |
|---|---|---|
| Selected tab/speed text | `#4db8a8` / `#0d2e28`; **6.07** | `#1a6e60` / `#c8e8e0`; **4.67** |
| Board coordinates | `#a89880` / `#1a1710`; **6.36** | `#4a3e30` / `#e8dfcf`; **7.85** |
| Player role text | `#a89880` / `#161310`; **6.58** | `#4a3e30` / `#ede7da`; **8.43** |
| Analysis/chart labels and axes | `#a89880` / `#0e0c0a`; **6.94** | `#4a3e30` / `#f7f3ec`; **9.39** |
| Enabled Start action | `#0e0c0a` / `#4db8a8`; **8.12** | `#ffffff` / `#1a6e60`; **6.08** |
| Board grid boundary | `#735538` / `#d4a76a`; **3.09** | Same; **3.09** |
| Focus indicator against primary surface | `#7eb8d4` / `#0e0c0a`; **9.01** | `#1a5c80` / `#f7f3ec`; **6.58** |
| Meaningful chart series | `#4db8a8` / `#0e0c0a`; **8.12** | `#1a6e60` / `#f7f3ec`; **5.51** |
| Offline alert, composited surface | `#ff6b5a` / `#271412`; **6.27** | `#9e1f1f` / `#ead3cd`; **5.51** |
| Reconnect alert | `#ff6b5a` / `#161310`; **6.61** | `#9e1f1f` / `#ede7da`; **6.38** |

Matrix rate-cell text over actual translucent red/green fills also passed: dark minimum 10.39:1, light minimum 11.02:1. See [composited cell measurements](evidence/matrix-contrast.json).

### Screenshots

| View | Before | After dark | After light |
|---|---|---|---|
| Training desktop | [Before](screenshots/before-training-desktop.png) | [After](screenshots/final-training-dark-1440x900.png) | [After](screenshots/final-training-light-1440x900.png) |
| Training phone | No baseline captured | [After](screenshots/final-training-dark-390x844.png) | [After](screenshots/final-training-light-390x844.png) |
| Watch desktop | [Before](screenshots/before-showcase-desktop.png) | [After](screenshots/final-showcase-dark-1440x900.png) | [After](screenshots/final-showcase-light-1440x900.png) |
| Watch phone | [Before](screenshots/before-showcase-mobile.png) | [After](screenshots/final-showcase-dark-390x844.png) | [After](screenshots/final-showcase-light-390x844.png) |
| League desktop | [Before](screenshots/before-league-desktop.png) | [After](screenshots/final-league-dark-1440x900.png) | [After](screenshots/final-league-light-1440x900.png) |
| League phone | [Before](screenshots/before-league-mobile.png) | [After](screenshots/final-league-dark-390x844.png) | [After](screenshots/final-league-light-390x844.png) |

Before images come from the original representative client-data review. After images use the disposable real-server fixture; these compare layout, not an identical game position. Additional 200% text screenshots are alongside them.

## Delivery custody

Branch: `codex/web-ux-remediation`, based on `main` at `1a451a2`. Backend/fixture commit: `4fca4bb`; frontend/tests/changelog/README commit: `62588c3`. This documentation and screenshots form a separate evidence commit.

Generated production assets under `keisei/server/static/` are ignored by the repository and were built for verification; they are not source changes. No live training database was changed, and no trainer/sidecar was restarted. Unrelated `shogi-engine/CLAUDE.md` was preserved. Local commits, independent review and fixture acceptance are complete; merge, push/PR, remote CI and deployment were not performed or claimed.

## Subsequent PR publication verification

The user subsequently authorized publishing and merging through [PR #75](https://github.com/foundryside-dev/keisei/pull/75). Publication branch `codex/web-ux-publication` starts from remote `main` at `7c11e17`; it carries only the three UX commits, cherry-picked as `950bd81`, `204b0b7` and `0d5afa5`. The unrelated unpublished unified-planning commit `1a451a2` remains preserved on its existing local branch/worktree. Runtime source matches the reviewed implementation.

Initial hosted CI exposed a stale boundary-test fixture mocking the old runner inference function and omitting the initial ply. The fixture now supplies the qualified-evaluation contract and asserts the pre-move arguments while retaining every decisive-outcome assertion. Runtime behavior was unchanged. The repaired checkout passes **34 focused Showcase tests** and the CI-equivalent fast gate: **1,244 Python tests passed** (`pytest -x --tb=short -q -n 2 -m "not slow and not integration"`, Python 3.13). Ruff passes for the repaired test. Hosted Web UI, Rust, lint and type checks passed on the initial PR run. Final hosted checks and merge state are recorded on the PR and in Filigree publication task `keisei-b55bb75e4d`; this section does not predeclare their result.
