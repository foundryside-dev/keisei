# Web UX remediation implementation plan

Status: reviewed and authorized for execution by the later user instruction to implement, use Astra for review, and confirm with Playwright. Source baseline: `main` at `1a451a2`, inspected 2026-10-10 (Australia/Canberra). Planning task: `keisei-1c97b2a405`. Execution milestone: `keisei-de3922e0d9`. Execution state belongs in Filigree; this file defines the work, not a parallel status log. Independent UX review: **ready**, after resolving two conditions and recheck; see [review record](2026-10-10-web-ux-remediation.review.md).

## Outcome and scope

Make watching a shogi game the primary experience, make league investigation easier, and make all spectator controls and position information usable with a keyboard and assistive technology. Cover all seven recommendations from review `keisei-884b5330fb`.

Execution will change the existing Svelte 4 application and the small Python/SQLite/API contracts needed for honest evaluation and saved-match links. Preserve the wood/ink palette, both themes, opt-in audio, reduced-motion behavior, server command acknowledgements, and completed-game retention. No framework migration, training/model changes, benchmark research implementation, live database reset, restart, deployment, or publication is part of this plan.

The plan itself did not authorize implementation. The user subsequently instructed execution with Astra review and Playwright confirmation; that instruction authorizes the bounded implementation and validation below.

## Source findings that constrain implementation

| Evidence at the baseline | Consequence |
|---|---|
| `App.svelte:270-275,414-420` locks the app to the viewport and stacks thumbnails/player cards ahead of the board below 1800px; `MetricsGrid.svelte` reserves fixed chart heights | UX01 must change shell priority and scrolling, rather than just shrink fonts |
| `Board.svelte:101-105` sizes squares from viewport width; `ShowcaseView.svelte:335-349` centers a nonshrinking board inside clipped content | UX02 needs container sizing and a short-height fallback |
| `ShowcaseView.svelte:91-112` handles replay keys on window; `MoveLog.svelte:45-50` also handles Space | UX03 must preserve native activation and avoid double handling |
| `runner.py:135-142,177-205` evaluates before stepping and saves the value with the post-move board/current player | UX04 must name evaluation position and player explicitly |
| `inference.py:64-100` maps scalar output to `(v+1)/2`, but multi-head output to `P(win)` | These values cannot be relabelled as one comparable Black win probability, or complemented across draws |
| `HistoricalLibrary.svelte:64` shows five epochs, while `db/league.py:171-182` loads only the latest 50 distinct epochs | UX05 needs actual older-history retrieval, not only a client-side “show more” button |
| `navigation.js` persists only a tab; server `/` uses `StaticFiles(html=True)` | UX07 will use root query URLs, which reload without adding a path-routing fallback |
| `db/showcase.py` already reads games by ID, but WebSocket init/poll selects the latest game | Saved-match links need a read-only lookup and separate displayed-match state |

The earlier review screenshots in `output/playwright/` use representative client-side data, not live acceptance evidence. Reproduce with a fixture matching actual payload fields before implementation; retain those screenshots as baseline evidence only.

Existing unified remediation packages U16 (`keisei-13ed0d0d8c`) and U17 (`keisei-1fe7bab768`) own benchmark progress/calibration, rating provenance and benchmark replay. This plan fixes existing spectator UX and leaves those packages intact. Use the same principle of qualified model estimates; do not introduce a second benchmark store or overload its future identities. Coordinate edits to `App.svelte`, `EntryDetail.svelte`, chart helpers and navigation at integration time. No dependency on the entire research milestone is required.

## Chosen interaction and layout contracts

- Keep internal view IDs `training`, `league`, `showcase`, `about`. Visible Showcase label becomes **Watch match**; its setup action remains **New match**. Training keeps its name because it contains both live training games and metrics.
- Desktop Training has a game-selector rail, a central selected board with a compact player strip, and secondary move/details content. A collapsed **Training metrics** disclosure follows the viewer. Expanded charts use normal reachable scrolling; they never shrink the viewer to a sliver.
- Below 1024 CSS px, use one primary column: player strip, board, game-selector disclosure, moves/details, metrics. The selector shows the current game and “Choose game (N)” while collapsed. List all loaded games; remove the first-16 selection limit. It is a live lane selector, not an archive.
- At ordinary desktop sizes, board, both hand trays and essential controls fit the viewer. On phones/short-height or zoomed layouts, use document flow and a complete width-fitting board; scrolling is acceptable and no upper ranks may be clipped. Do not make the board unreadably small to fit every surrounding panel above the fold.
- Header always exposes app/run identity, connection/trainer state, epoch and navigation. Detailed counters, clocks, CPU/GPU and architecture move into a **Run details** disclosure. Player name, side/role and rating remain visible; topology, auxiliary metrics and flavour facts use **Player details**. Disclosures are closed initially and keep their state during live updates.
- Show **Live**, **Paused at ply N**, **Replay · ply N**, or **Finished** explicitly. Pinning pauses the viewer, not the engine. Controls use that wording; completed games never claim a live stream.
- Missing/invalid evaluation is **Estimate unavailable**, with a reason. Do not draw a neutral 50% line or a zero value as a fallback.
- Navigation and focus are deliberate user actions. Feed updates may update data without stealing focus, changing the selected archived match, or unexpectedly scrolling the document.

## Work packages and dependency graph

| Package | Review item | Prerequisites | Existing execution issue |
|---|---|---|---|
| UX01 — Training viewer and shared shell | 1; layout foundation for 7 | None | `keisei-40024f87c0` |
| UX02 — Complete Showcase board and controls | 2 | UX01 | `keisei-a0583cc542` |
| UX03 — Replay keyboard behavior | 3 | None | `keisei-79612268b8` |
| UX04 — Qualified, correctly oriented evaluation | 4 | None | `keisei-b780c7e0a3` |
| UX05 — League investigation and older history | 5 | UX01 | `keisei-a563eb3d68` |
| UX06 — Accessible positions and focus restoration | 6 | UX03, UX04, UX05 | `keisei-3d4b6a94d6` |
| UX07 — Density, labels and shareable navigation | 7 | UX02, UX03, UX05, UX06 | `keisei-2bb30687ad` |
| UX08 — Integrated acceptance and delivery evidence | All | UX01–UX07 | `keisei-c46dbacb91` |

The prerequisites are code/integration dependencies, not mandatory parallel work. UX03 and UX04 can be implemented independently; shared-file edits still require integration review. Seven recommendations map to seven fix packages; UX08 is their shared acceptance gate.

### UX01 — Put the selected Training game first

Modify `webui/src/App.svelte`, `app.css`, `lib/StatusIndicator.svelte`, `PlayerCard.svelte`, `MetricsGrid.svelte`, `GameThumbnail.svelte`, `lib/ws.js`, `stores/games.js` and affected render/store tests. Extract `TrainingView.svelte` and a small reusable viewer-layout component only where it reduces duplicated shell/sizing logic.

1. Replace the 1800px all-or-nothing stack with the desktop/compact layout above. Remove thumbnail width derived from panel height; size the rail from available width and its own scroll region.
2. Put player identity and board ahead of expanded biographies and thumbnails in compact DOM order. Use CSS areas for desktop arrangement, keeping reading and focus order logical.
3. Move expanded metrics out of the viewport grid's reserved bottom row. Make its disclosure keyboard operable and label its open state. Retain chart functionality without recreating charts on every heartbeat.
4. Establish the compact header/Run details and Player details structures now; UX07 completes labels, URL wiring and density verification. Keep counters accessible without tooltip-only disclosure.
5. Make every loaded training game selectable, including lane 17+. Training selection follows a **lane**, not a durable archived match: keep the selected lane on game completion and remove the existing end-of-game auto-switch to a different lane. A new game reusing that same lane may advance its board and reset move display, with a concise “New game in lane N” status. If the selected lane disappears, select the lowest-ID active lane (otherwise lowest-ID available lane), update `selectedGameId` consistently and announce the fallback. An empty set selects no lane. Do not change the trainer or fabricate historical games.

Acceptance: with 16 and 32 loaded lanes, long player names and populated metrics, the selected board is visible without scrolling at 1440×900 and 1280×800. At 390×844, the first board row is visible initially; the whole board and both trays are reachable in normal scrolling. Expanding metrics/player details does not hide controls or lose selection. Completion, same-lane replacement, selected-lane removal and zero lanes follow the policy above without mismatched selected highlights. Empty/loading/disconnected views explain the state and a useful next action. All loaded lanes are selectable.

Checks: extend `App.render.test.js`, `stores/games.test.js` and `lib/ws.test.js` for completion/replacement, missing selection on reconnect, fallback and empty snapshots; add focused `TrainingView.render.test.js` if extraction occurs. Use browser geometry/screenshots for responsive acceptance; jsdom is not layout evidence.

### UX02 — Fit Showcase to its container

Modify `Board.svelte`, `ShowcaseView.svelte`, `MatchScorecard.svelte`, `ShowcaseStatsBanner.svelte`, `MatchQueue.svelte`, `MatchControls.svelte` and theme foreground/background pairings in `app.css`; reuse the UX01 layout contract. Add focused sizing helper tests only if sizing logic is extracted into JS.

1. Give Board a container-based size input or CSS custom property with a safe standalone fallback. On desktop compute available size after header, compact scorecard, trays and controls; do not use only `100vw`.
2. Compress engine/queue/ply summary into a status strip; preserve offline alerts, queue-full feedback and named players. Place essential replay controls directly after the board. Correct action foreground/background pairs while restyling: white on dark-theme teal `#4db8a8` is only about 2.40:1 in the current Start Match button. Choose a readable dark foreground or darker fill and verify both themes against the UX08 contrast checks.
3. At narrow or short-height viewports switch to document flow. Remove center-alignment/overflow combinations that place the top of a tall child above its scroll origin. Moves, commentary and queue remain reachable without shrinking to zero.
4. Preserve live-tail/pinned selection and completed-game retention. Show explicit viewer state; label Space as **Pause/resume following** rather than pausing the match engine. Use **Latest move** for finished-match tail controls.

Acceptance: all 81 squares, coordinate labels, trays and replay controls are visible together at 1440×900 and 1280×800. At 390×844, 320×568 and 844×390 they are reachable in order, without clipped ranks or document-level horizontal overflow. Enlarged text does not make controls overlap the board. New moves and resize do not reset a pinned ply.

Checks: new `ShowcaseView.render.test.js` for state labels/controls plus existing `stores/showcase.test.js` and `lib/MatchControls.render.test.js`; browser resizing is required for clipping assertions.

### UX03 — Make replay shortcuts cooperate with native controls

Modify `ShowcaseView.svelte` and `MoveLog.svelte`; extract `lib/replayKeyboard.js` if useful for isolated key-policy tests.

1. Scope replay key handling to a focusable, labelled viewer region. Ignore `defaultPrevented`, modifier chords, form controls, links, native buttons and elements with interactive roles (including tab and button roles). Do not capture tablist arrows/Home/End or scrollable move-log navigation.
2. Replay region keys: arrows step one ply, Shift+arrows five, Home first stored position, End latest, Space pause/resume following, H heatmap. Advertise them near the region, and provide buttons for every action. No global single-character shortcut is required.
3. Move cells handle Enter/Space once and keep the selected historical ply. Native buttons continue to accept Enter/Space. Tab switching unmounts replay handling cleanly.
4. Separate **following** (`selectedPly == null`) from **selected position happens to equal latest**. Pausing at the latest existing ply must display Paused immediately and remain there when another move arrives. Selecting or scrubbing to the latest ply remains pinned; only the explicit Live/End/resume action enables following. Update `stores/showcase.js` and every consumer of `isScrubbing` so labels/announcements/selection use this distinction consistently.

Acceptance: Space activates Heatmap/New match/audio controls normally; tablist keys navigate tabs; Space on a historical move selects it without jumping to live. Replay-region shortcuts work, inputs retain typing/selection behavior, and paused position remains stable as new moves arrive. Pause at the newest ply, append a move, and verify the board remains pinned and the label was Paused even before the append; explicit Resume/Live restores following.

Checks: add `replayKeyboard.test.js` if extracted and browser-oriented `ShowcaseView.render.test.js`/`MoveLog.render.test.js` behavior cases. Confirm native activation in a real browser; synthetic key dispatch alone does not prove it.

### UX04 — Define evaluation meaning before displaying it

Modify `keisei/showcase/inference.py`, `runner.py`, `keisei/db/showcase.py`, `_migrations.py`, `db/__init__.py`, server serialization as necessary; frontend `stores/showcase.js`, `CommentaryPanel.svelte`, `WinProbGraph.svelte`, `ShowcaseView.svelte`. Keep Training's existing scalar `EvalBar` behavior separate unless its contract is independently verified.

1. Introduce a versioned evaluation object returned by Showcase inference and persisted as nullable `showcase_moves.evaluation_json`. Fields: version, kind (`outcome_score`), score in [0,1], evaluated player, evaluated position ply, source architecture/contract; optional W/D/L probabilities for multi-head models. Preserve the existing `value_estimate` field's old meaning for older consumers; the new spectator analysis reads the explicit object only.
2. Define outcome score as `(v+1)/2` for scalar models and `P(win)+0.5*P(draw)` for WDL models. It is a model estimate, not calibrated win probability. Keep policy/top-candidate probabilities distinct.
3. Capture player and position ply **before** `env.step`. Persist that metadata with the move record; it explicitly describes the position before the displayed move. Use the common label **Black outcome estimate before move N**. Convert White-perspective outcome score with `1-score`; this complement is valid for this score, unlike bare `P(win)` when draws exist. A subtle note says estimates alternate between the players' models.
4. Derive commentary, Showcase eval bar and graph from one validated helper, e.g. `lib/showcaseEvaluation.js`. The graph uses evaluated position ply, explains the timing, and selects the associated stored move when clicked. Provide an adjacent accessible value/position list rather than a pretend Enter handler that requires pointer coordinates.
5. Add an idempotent additive migration using the next available schema version at execution time. Legacy rows remain NULL; malformed/unknown-version/non-finite/out-of-range evaluations render an unavailable state or graph gap, never inferred WDL or fabricated neutral output. Replay remains usable.

Acceptance oracles: scalar +0.6 for Black yields 0.8; the same score for White yields Black 0.2. W/D/L [0.2,0.7,0.1] yields player score 0.55 and opposite score 0.45. Switching the post-move current player must not flip that stored evaluation a second time. All-draw predictions are neutral; missing legacy data is unavailable. Graph, text and bar agree at a selected historical move.

Checks: extend `tests/test_showcase_inference.py`, `test_showcase_runner.py`, `test_showcase_db.py`, `test_server_showcase.py`; add `showcaseEvaluation.test.js` and extend `stores/showcase.test.js`. Use a temporary database upgrade fixture and repeat initialization to verify migration idempotence. No live DB mutation during tests.

### UX05 — Make League investigations bounded and discoverable

Modify `LeagueView.svelte`, `LeagueTable.svelte`, `MatchupMatrix.svelte`, `HistoricalLibrary.svelte`, `stores/league.js`; add a narrow history API helper/store, `keisei/db/gauntlet.py` reader and `server/app.py` route. Add `/api` to the Vite proxy.

1. Compress mobile summary cards into a wrapping summary strip; the leaderboard heading and at least one row must be visible at 390×844 with representative names and counters.
2. Add a labelled player filter for head-to-head results. All-players mobile view emits each unordered pair once, with an explicit **record from [player] perspective**. A selected-player view places that player first and swaps W/L appropriately. Keep trainer aggregate visibly separate from individual entries and exclude its own snapshots as today. Full names wrap; duplicate display names also expose stable entry IDs/epochs.
3. Keep the desktop matrix for comparisons, with full accessible row/column names and numeric W/L/D information independent of color. Provide the same filtered record list as a keyboard-readable alternative. Show distinct “no games for this filter” and “no matchup data yet” states.
4. Label gauntlet history **Latest 5 evaluations** initially. Add **Load 5 older evaluations** with a read-only cursor endpoint `/api/league/gauntlet?before_epoch=E&limit=5`. Register the route in `create_app` before the catch-all static mount. Query five distinct epochs, return every slot row for each epoch, plus `next_before_epoch` and `has_more`; validate limit 1–50. Support history older than the WebSocket's latest-50 window.
5. Merge/deduplicate pages by persisted result ID; preserve already loaded epochs and scroll when live updates arrive. Provide loading, retry and end-of-history states; reject stale responses after relevant context changes. Do not imply that an unevaluated epoch has a score.

Acceptance: A/B appears once in All players and in the selected player's perspective when filtered; draws and totals remain correct. Two long similarly named snapshots are distinguishable. Six, 51 and zero evaluation epochs exercise paging without splitting a single epoch's results. New live results neither erase older pages nor duplicate rows; a failed page load keeps existing data and offers Retry.

Checks: new `matchupRows.test.js` if helper extracted, `MatchupMatrix.render.test.js`, `HistoricalLibrary.render.test.js`, `tests/test_server_gauntlet_history.py`; extend league-store tests. Verify small/touch layouts in the browser.

### UX06 — Expose positions and restore focus

Modify `Board.svelte`, `pieces.js`, `LeagueView.svelte`, `LeagueTable.svelte`, `EntryDetail.svelte`, and relevant viewer adapters. Add a `boardPosition.js` helper and `BoardPosition.svelte` if they keep the visual board component small.

1. Add **Position as text** beside every full game board. Use an accessible table/list of occupied squares with file/rank, side, English piece name and promotion status; include hands and side to move. Offer empty-square detail if requested without dumping 81 live announcements. Text and visual board must derive from the same displayed position, including replay.
2. Keep compact thumbnail accessibility summaries; do not put a position table under every thumbnail. Announce a concise move/position change politely, with an explicit follow-announcements toggle; pausing/scrubbing does not produce uncontrolled announcements.
3. On entry opening remember the initiating row/control and focus the detail heading after rendering. Close/Escape restores that row if still present; otherwise focus the leaderboard heading with a clear status message. For a direct entry URL with no initiating control, use the heading fallback.
4. Complete tab/tabpanel relationships for all views and ensure skip links reach their primary region. Keep focus rings and reduced motion; graph data must have a non-canvas route (UX04), not chart-only navigation.

Acceptance: a keyboard/screen-reader user can identify both kings' squares, a promoted piece, held pieces and the side to move at a selected ply. Close and Escape return to the correct row after sorting/live updates; if the entry disappears, focus remains meaningful. Feed updates do not steal focus or announce every square. Existing native controls remain operable.

Checks: new `boardPosition.test.js`, `Board.render.test.js`; extend `LeagueView.render.test.js`, `LeagueTable.render.test.js`, `App.render.test.js`. Manual keyboard traversal and an actual available screen reader are required; if no screen reader is available, report that limit and keep that acceptance item open. Execution disposition authorized by the user: mark the real screen-reader check **Unable to test** (neither the environment nor user has one), retain follow-up `keisei-ebe3c4bef2`, and deliver the implementation with that limitation explicit.

### UX07 — Finish density, labels and durable navigation

Modify `StatusIndicator.svelte`, `TabBar.svelte`, `PlayerCard.svelte`, `App.svelte`, `stores/navigation.js`, `stores/showcase.js`, `lib/ws.js`; add a separate viewed-match/replay adapter, read-only API route(s) and Vite `/api` proxy. Update About references to the renamed view and document links in `webui/README.md`.

1. Complete the Run details/Player details disclosures from UX01; display **Watch match** consistently. Audio and theme remain labelled controls, grouped outside `role=tablist`. Preserve visible connection/stale/offline/pending feedback in every view.
2. Root query contract: `/?view=league&entry=42`, `/?view=showcase&match=123&ply=17`, `/?view=training`, `/?view=about#about-big-idea`. IDs remain internal, avoiding any dependency on SPA path rewrites. No URL means validated saved-tab fallback, otherwise Training; an explicit URL wins over localStorage.
3. User tab/entry/match choices use `pushState`; repeated scrubbing uses `replaceState`; feed updates never create history entries. Handle `popstate` without write loops, preserve unrelated query/hash state, validate positive IDs and actual stored ply values, and clamp only out-of-range numeric ply with visible feedback. Invalid or missing match/entry gets a recoverable unavailable state, not a silent switch to different data.
4. Add read-only `GET /api/showcase/games/{game_id}` returning metadata and ordered stored moves. Register the route in `create_app` before the catch-all static mount. Current games are bounded by 512 plies; enforce a documented 2048-move response ceiling for legacy/corrupt data and return a clear error above it rather than truncate. Validate IDs; return 404 for absent games. Existing DB readers supply the data without loading any model or writing the DB.
5. `view=showcase` without a match follows the latest feed. An explicit match pins identity; missing ply follows that match's tail, numeric ply pins its stored position. New live games must not replace the viewed match. Archived retrieval uses separate state so live init/poll cannot overwrite it; abort or generation-check stale requests. Include **Watch latest match** recovery and a labelled **Copy link** action with success/failure feedback.
6. Archived matches show **Replay** and cannot change the speed of an unrelated running match. New-match setup can remain available, but submitting it must not navigate away from archived replay without an explicit user choice. Preserve current command feedback and request correlation.

Acceptance: copied league/match links open the same entity/ply in a fresh browser session; reload and Back/Forward work. About anchors work with query views. Malformed, missing and retired IDs have useful states; duplicate names do not affect identity. A late response for match A cannot replace match B; reconnect/new-game events do not reset pinned replay. No autoplay audio or unexpected focus changes follow reload. CPU/GPU values remain discoverable in at most one disclosure action.

Checks: extend `stores/navigation.test.js`, `stores/showcase.test.js`, `lib/ws.test.js`, `App.render.test.js`; new `viewedMatch.test.js`, `tests/test_server_showcase_history.py`; test endpoints on temporary DBs and reload links against the built FastAPI-served UI, not only Vite.

### UX08 — Integrated acceptance and delivery

Use a representative deterministic fixture matching current server payloads, and a disposable SQLite fixture for history/deep-link checks. Reuse existing frontend test and browser tooling; no framework/toolchain migration or third general-purpose harness. Record task progress and evidence in Filigree, not ad-hoc notes.

1. Cover no data, connecting, disconnected/stale, active match, finished match, engine offline, command pending/error, paused/replay, history loading/error/end and unavailable legacy evaluation. Include 32 training lanes, 20 league entries, long/duplicate names, 51 history epochs, draws and a promotion/drop position.
2. Browser matrix: 1920×1080, 1440×900, 1280×800, 768×1024, 390×844, 320×568 and 844×390. Check both themes on the principal desktop/phone sizes, text at 200%, effective 320 CSS px reflow, keyboard-only use, reduced motion, and touch targets. Essential controls should be at least 44×44 CSS px; preserve board semantics when a two-dimensional board itself cannot reflow. Measure resolved foreground/background pairs, including opacity/overlays: at least 4.5:1 for ordinary active text, 3:1 for large text (24 CSS px normal or about 18.7px bold), and 3:1 for necessary control boundaries/state and focus indicators against adjacent colors. Cover primary action text, selected controls, alerts, board coordinates, chart axes/labels and meaningful series; semantic states must also have text/icons, not color alone. Fix affected pairs while preserving the wood/ink palette; report actual pairs/ratios rather than a theme-wide compliance claim.
3. At normal desktop sizes the entire primary board/trays/replay controls fit. In narrow/zoomed modes content is reachable in logical document flow without clipped board rows, lost focus, or document-level horizontal scrolling. Expansion never makes a panel permanently unreachable.
4. Walk three end-to-end tasks: choose a training game and inspect its position; watch/pause/scrub/resume a match; filter a league player, inspect old evaluations, open an entry and share a saved match/ply. Record whether each succeeds and which fixture/live data was used. Inspect console failures; missing backend/audio assets must be distinguished from product defects.
5. Update `CHANGELOG.md` under `[Unreleased]` and `webui/README.md` with delivered behavior and link semantics. Save final before/after desktop/mobile screenshots in `docs/reviews/web-ux-remediation/` only when execution occurs. Review changes independently before integration; record local tests, merge/PR, CI and deployment as distinct states.

Focused commands, run from the repository unless noted (new test paths become valid when their package is implemented):

```bash
# Each package runs its named affected tests first.
cd webui
npm test -- src/App.render.test.js src/stores/navigation.test.js src/stores/showcase.test.js
npm test -- src/lib/LeagueView.render.test.js src/lib/LeagueTable.render.test.js
# At UX08: full frontend regression and production compilation.
npm test
npm run build
cd ..
# Python contract packages UX04/05/07, then combined at UX08.
uv run pytest tests/test_showcase_inference.py tests/test_showcase_runner.py tests/test_showcase_db.py tests/test_server_showcase.py tests/test_server_gauntlet_history.py tests/test_server_showcase_history.py -q
uv run ruff check .
uv run mypy keisei/
git diff --check
```

`npm run build` writes `keisei/server/static/`; inspect generated changes and follow existing asset custody. Existing unrelated lint/type failures are recorded precisely; material failures introduced or exposed on affected paths are resolved. No full training experiment or Rust engine change is needed to verify these UX changes.

## Recovery, sequencing and review requirements

- Preserve unrelated `shogi-engine/CLAUDE.md`, previous review artifacts and other work. Use a branch from current `main` when execution starts, with Conventional Commits per bounded package. This planning task creates no branch/commit requirement.
- UX04 adds an additive DB migration. Validate on temporary/copy databases first. Roll back frontend packages by reverting their commit; schema rollback is not promised. Old application versions can refuse a newer schema, so a production rollback requires a compatible backup or forward fix. Do not delete/recreate a live database as part of this plan.
- No product choice blocks planning. Chosen labels, desktop/compact layouts, root query URLs and outcome-score semantics are the implementation defaults specified here; adjust only with evidence during review, keeping all acceptance outcomes.
- Before marking the plan ready, an independent UX review agent checks coverage of all seven recommendations, consistency of layout and focus behavior, cognitive load, touch/keyboard access, honest evaluation wording and testable acceptance. Parent resolves material findings and requests a focused recheck. Plan review is not implementation or runtime verification.
- Before closing execution milestone UX08, all package acceptance outcomes require evidence. Automated checks alone do not certify visual layout or screen-reader usability. Record unperformed checks openly; do not call the UI accepted while a required accessibility or core-flow check remains unverified. The later user-authorized screen-reader disposition above permits implementation delivery with that check recorded as Unable to test; it does not claim screen-reader acceptance.
