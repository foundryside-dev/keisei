# Claude Code Fable high merge review

Reviewed PR #75 merge `0908e56f76b6830c2875a3287b85bec6e9842200` against first parent
`7c11e17a250a088a6794293e6ebc4aa09b1490da` on 2026-10-10.
Invocation: `claude --print --model fable --effort high`, read-only Read/Glob/Grep,
plan permission mode, empty MCP configuration, no session persistence.
Resolved model: `claude-fable-5-1`; session
`083888f8-f520-4746-8fd9-82dfc842650c`. Completed successfully in 14.3 minutes,
with no permission denials. Claude also used its native advisor. It executed no tests.
Tracking: `keisei-c6be36286d`.

## Finding dispositions

| Finding | Disposition | Repair / evidence |
| --- | --- | --- |
| 1. Latest-feed pause/resume pins match identity | Fixed | Remember latest-feed intent only for local replay navigation. All resume affordances restore a null match ID; external navigation resets that intent, including history navigation to the same match. Explicit links keep their match. |
| 2. Future ply is labelled paused but advances | Fixed | Resolve an out-of-range position once and retain that actual ply across appends. This preserves the plan's paused-clamp behavior instead of silently enabling following. A new requested ply resets the clamp. |
| 3. Read-only SQLite busy timeout missing | Rejected with executed counterevidence | Python's raw `sqlite3.connect` already installs a 5000 ms busy timeout. Instrumented calls to both actual readers (`read_gauntlet_history` and `read_saved_showcase_game`) each reported `PRAGMA busy_timeout = 5000`. No redundant pragma or implementation-mirroring test was added. |
| 4. Pausing downloads the populated live match | Fixed | Skip the archive request when the matching WebSocket game has valid move history. Refresh still happens when the feed advances away from an explicitly viewed game. |
| 5. Malformed showcase link announces twice | Fixed | Showcase owns its route-error alert and recovery buttons; the root alert handles other views. |
| 6. Matchup list reports collapsed while expanded | Fixed | Shared effective expansion state drives presentation and `aria-expanded`. Automatically visible filtered/empty lists have an accurately labelled disabled toggle, avoiding a no-op Hide action. Unfiltered populated lists still toggle normally. |

Regression checks reproduced all five confirmed defects before the repairs.
Screen-reader validation remains **Unable to test**, as accepted by the user,
with follow-up `keisei-ebe3c4bef2`.

## Executed repair validation

- All 463 frontend tests in 46 files pass; production build succeeds.
- Ruff passes and mypy reports no issues across 68 source files.
- Chromium against a fresh disposable SQLite database and the real FastAPI /
  WebSocket server passes all five resume controls (Resume, Live, move-log return,
  End, Space), with no archive downloads on local pause.
- After an actual legal move is appended, an out-of-range paused link stays at
  ply 12 while the scrubber's maximum advances to ply 13.
- After an actual new match starts, latest-feed resume follows match 4; an
  explicit saved-match resume retains match 3 and its completed ply 13.
- Real browser Back to the same match clears temporary latest-feed intent;
  explicit identity survives a subsequent actual rollover. Resume after a rollover
  while paused catches up to the new latest match.
- A malformed URL has exactly one route-error alert and a working recovery action.
- Filtered disclosure has accurate expansion state and avoids a no-op Hide
  control. Manual Show/Hide works for all players. At 390x844 in the light theme,
  records remain visible with no horizontal document overflow.
- After the final focus repair, the real WebSocket empty-data transition leaves
  focus on the player filter (SELECT), instead of BODY as reproduced before it.
- Re-ran all 14 checks in the historical `keisei-ux-flows-2.js` browser script
  against the final build, including archive reload, 51 complete evaluation
  epochs / 255 rows, entry Close / Escape and browser Back focus restoration.
- Browser oracles and machine-readable results: [evidence/fable-results.json](evidence/fable-results.json).
- Screenshots: [paused clamp](evidence/fable-paused-clamp.png),
  [invalid-link recovery](evidence/fable-invalid-link.png),
  [filtered desktop](evidence/fable-filtered-matchups-desktop.png),
  [filtered phone](evidence/fable-filtered-matchups-phone.png).

The bounded Claude re-review **accepted** all five repairs and the SQLite
rejection, with no material new defect. It completed successfully as
`claude-fable-5-1`, high effort, session
`a3487536-0b73-422d-8610-537d6cbf3339`, with no permission denials. It also used
its native advisor. Full report follows below.

Follow-up details: refreshed the older browser oracle's clamp wording; strengthened
the clamp test to cover the originally requested ply actually becoming available;
and reproduced the reviewer's minor focus concern in Chromium (active element
became BODY after live matchup data emptied). The final focus repair moves focus
to the player filter before disabling the previously focused list toggle. Focus
checks only run when that toggle owns focus, so unrelated live updates do not
move it. Final validation and hosted integration CI are recorded in PR #76.

## Bounded Claude re-review

**Verdict: accept.** Nothing in the repair diff blocks. All five confirmed defects are fixed in the current checkout, the SQLite rejection is correct, and I found no material new defect. Everything below is static inference from source and tests. I ran nothing. The 463-test, build, Ruff, mypy, and PRAGMA results are parent-reported, and the browser checks are someone else's.

## Per-finding disposition

**1. Latest-feed pause pins identity: fixed.**
- The flag is set only from a non-explicit route at `webui/src/lib/ShowcaseView.svelte:91` and consumed at line 95, so resume sends a null match ID when the pause originated on the latest feed.
- Every resume affordance funnels through `selectIndex(-1)`: Resume/Space via `toggleFollowing` at line 105, End key at line 112, the tail button at line 155, and the move log's return button at line 171 through `MoveLog.svelte:89`.
- External navigation resets the flag through the subscription at lines 34 to 36. Popstate goes through `readHistory` at `webui/src/stores/navigation.js:91`, which publishes even for the same match ID, so history navigation to the same match retains explicit identity. Local scrubs are shielded by `selectingPosition`, which is set before the synchronous store write at line 97.
- A scrub after a latest-feed pause is already explicit, so line 91 neither sets nor clears the flag. That is the intended behavior.
- Tests at `ShowcaseView.render.test.js:163`, `:175`, and `:190` cover all five controls, explicit retention via popstate, and resume after rollover while paused.

**2. Future ply drifts while labelled paused: fixed.**
- The clamp resolves once at `webui/src/stores/viewedMatch.js:62` to `:66` and later publishes reuse `clampedPly` at line 59, so the board stays at the clamped ply across live appends with `following` still false at line 57.
- The clamp resets on any match, ply, or view change at line 127, so a fresh link retries. Test at `viewedMatch.test.js:127`.
- Non-blocking design note: once clamped, the originally requested ply is never retried even after it is played. A shared link to ply 50 opened at ply 30 stays at 30 permanently. That matches the stated plan, but it is a real change for the sharing case and is untested in that form. The one-line alternative is to try `route.ply` first and fall back to `clampedPly`. Your call.

**3. SQLite busy timeout: rejected, correctly.**
- The original finding's premise was wrong, not just unproven. Python's `sqlite3.connect` default `timeout=5.0` installs a 5000 ms busy handler on every connection, so the explicit pragma at `keisei/db/_connection.py:11` is redundant with the default. The raw connections at `keisei/db/gauntlet.py:35` and `keisei/db/showcase.py:308` were never inconsistent with the helper. The same applies to the raw connect at `keisei/server/app.py:107`.
- Any WAL-recovery window that bypasses the busy handler would affect the helper's readers identically, so no differential risk remains. Executed PRAGMA evidence is parent-reported.

**4. Pause downloads the populated live archive: fixed.**
- The skip at `viewedMatch.js:95` publishes without fetching when the route matches the live game and its moves are present. The identity-change refresh at line 140 still fetches once the feed moves on.
- The skip depends on the WebSocket move list being complete. That holds by server design: init sends all moves at `keisei/server/app.py:350`, updates are contiguous from the sent cursor at lines 640 to 646, the cursor resets to zero on game change at line 635, and `webui/src/lib/ws.js:225` replaces rather than merges on game change. The guard at `viewedMatch.js:36` handles the transient window between the game store and the moves store updating.
- Covered by the component test at `ShowcaseView.render.test.js:185`. There is no direct unit test of the skip in `viewedMatch.test.js`. Minor gap.

**5. Malformed showcase link announced twice: fixed.**
- The root alert is suppressed for the showcase tab at `webui/src/App.svelte:168`. The showcase alert at `ShowcaseView.svelte:133` is the only remaining renderer of the route error in that view, and it keeps the Watch latest match button. Test at `App.render.test.js:113`.

**6. Matchup toggle misreports expansion: fixed.**
- Shared state at `webui/src/lib/MatchupMatrix.svelte:8` to `:9` drives `aria-expanded`, `disabled`, and the label at lines 147 to 148 and the panel class at line 150. The disabled toggle reads "Showing matchup record list", so Hide can no longer be a no-op. Test at `MatchupMatrix.render.test.js:41`.
- Nit, non-blocking: if the toggle holds focus when head-to-head data empties, disabling drops focus to the body. Rare, out of scope.

## Adjacent items worth knowing

- **Stale browser-evidence assertion.** The earlier acceptance script at `docs/reviews/web-ux-remediation/evidence/keisei-ux-flows-2.js:14` waits for the old text "Ply 999 is outside this match". The store now emits "was outside the available range" at `viewedMatch.js:69`. Re-running that script against the repaired build will fail on that step. The newer evidence file `fable-results.json:33` already uses the new wording. Not run by me.
- **Test count arithmetic is consistent.** The diff adds 11 tests, which matches the parent-reported 452 to 463.
- **Screen-reader validation** remains the user-accepted Unable to test item. No change in this diff affects that status.

No tracker state, files, commands, or external services were touched.

## Original Claude report

**Verdict: mergeable as shipped, with one Medium follow-up.** Nothing I found is a security issue, data-corruption risk, or crash. The server/store contracts for evaluation, archive identity, pagination and navigation hold up under tracing. The Medium item is a stale-state defect in the pause/resume flow that the existing tests do not cover. All conclusions below are static inference from source and tests. I ran nothing.

## Ranked findings

**1. Medium. Pause then Resume from the latest feed silently pins the viewer to a match ID.**
- `webui/src/lib/ShowcaseView.svelte:83` pins with `game.id`, and `webui/src/lib/ShowcaseView.svelte:81` resumes with `game.id` because `explicitMatch` is now true.
- `webui/src/stores/viewedMatch.js:49` derives `explicitMatch` from the URL alone, and `webui/src/stores/viewedMatch.js:131` reloads the old match when the feed moves on.
- Trigger: open `/?view=showcase`, press Space twice, or click Pause following then Resume following, Live, End, or the move log's return button. The URL now carries `match=N` with no ply.
- Observed path: label reads Live while match N runs. When match N ends and N+1 starts, the adapter keeps N, marks it archived, and shows "Replay · ply N" with a Watch latest match button. The user never chose to pin an identity.
- Impact: the core watch flow stops following new matches after any pause. The plan says a showcase view without a match follows the latest feed, and that resume re-enables following.
- Existing coverage: the render test at `webui/src/lib/ShowcaseView.render.test.js:57` asserts only the Live label after resume. The Playwright script `state-01-pin.js` started from an explicit match.
- Repair: keep a component-local flag set when pinning from a non-explicit route, and on resume call `setReplayPly(null, null)` when the flag is set. Clear it on Watch latest match or when the route's match ID changes elsewhere.
- Oracle: from `/?view=showcase`, Pause then Resume leaves navigation at `{matchId: null, ply: null}`, and swapping the live stores to game 10 shows game 10 with label Live. From `/?view=showcase&match=9&ply=2`, Resume keeps match 9.

**2. Low. An over-range ply on an in-progress match says Paused while the board keeps advancing.**
- `webui/src/stores/viewedMatch.js:60` clamps to the last move on every publish while `following` stays false at `webui/src/stores/viewedMatch.js:56`.
- `webui/src/lib/ShowcaseView.svelte:59` therefore renders "Paused at ply N" with N changing each move.
- Trigger: open `/?view=showcase&match=N&ply=999` while match N is live.
- Impact: contradictory passive state. Any scrub click normalises it. The archive case is tested at `webui/src/stores/viewedMatch.test.js:58`; the live case is not.
- Repair: in `publish`, when the requested ply exceeds the tail of an in-progress game, expose `following: true` and a status such as "Ply 999 is not played yet. Following the latest move."
- Oracle: route (1, 99) with a live in-progress game and moves 1 to 3, then append move 4. Today the result is displayed move 4 with `following: false`.

**3. Low. New read-only SQLite connections omit the busy timeout.**
- `keisei/db/gauntlet.py:96` and `keisei/db/showcase.py:308` open raw connections, while `keisei/db/_connection.py:11` sets a 5 second timeout for every other reader.
- Trigger: a WAL checkpoint or wal-index recovery by the trainer at the moment of an API read. Uncertain frequency. WAL readers rarely block, so this is a static inference about a narrow window.
- Impact: an immediate "database is locked" becomes a 500, shown as "Could not load older evaluations" or "Could not load match N (500)". Retry recovers.
- Repair: set the same busy timeout pragma on both connections.
- Oracle: assert the pragma value on the connection in the two API tests. A deterministic lock reproduction is not practical.

**4. Low. Every pause from the live feed fetches the full archive of the current game.**
- `webui/src/stores/viewedMatch.js:122` treats the new match ID as an identity change and `webui/src/stores/viewedMatch.js:92` issues the request even when live moves for that game are already present.
- Impact: wasteful, not incorrect. Up to 512 moves with boards and heatmaps per pause. After fix 1 it recurs on each pause.
- Repair: in `load`, publish and return when the route matches the live game and live moves exist.
- Oracle: live game 1 with moves, then navigate to route (1, 2). The fetch mock is not called. Existing tests that start without a live game keep their single fetch.

**5. Low. A malformed showcase link is announced twice.**
- `webui/src/App.svelte:168` and `webui/src/lib/ShowcaseView.svelte:117` both render the same route error as `role="alert"`.
- Repair: suppress the text in one location and keep the recovery buttons.
- Oracle: with `?view=showcase&match=bad`, exactly one alert contains "invalid match".

**6. Low. The matchup record list toggle misreports its expanded state.**
- `webui/src/lib/MatchupMatrix.svelte:145` sets `aria-expanded` from the toggle only, while `webui/src/lib/MatchupMatrix.svelte:148` also expands for a selected player or no records.
- Repair: use the same expression for both.
- Oracle: select a player and assert `aria-expanded="true"` on the toggle.

## Verified correct

- All four prior fixes hold: forward at the live tail at `webui/src/lib/ShowcaseView.svelte:86`, no next-turn text for terminal games at `webui/src/lib/MatchScorecard.svelte:78`, revision-keyed lane status at `webui/src/App.svelte:172`, and no Retry for malformed routes at `webui/src/stores/viewedMatch.js:76`.
- Evaluation semantics: player and ply are captured before the step at `keisei/showcase/runner.py:142`, the client requires the position ply to equal the move ply minus one, Black orientation is a single complement, WDL half credit matches server and client, and invalid data becomes unavailable with no neutral fallback. Live and archive rows share the same column shape, so the evaluation field reaches both paths.
- Migration is additive and idempotent with the version bump and DDL column in place.
- Both API routes use parameterised SQL, validate bounds, return 404, 413 and 422 as documented, register before the static mount, and open the database read-only so a missing file is never created.
- Pagination returns complete epochs, derives `has_more` from one extra epoch, and the client deduplicates by persisted ID, preserves older pages, and rejects stale responses by generation.
- The viewed-match adapter aborts superseded requests, checks response identity, merges live and archive moves by ply, and ignores work after destroy.
- Navigation validates syntax only, pushes for choices and replaces for scrubbing, reads popstate without writing, and preserves unrelated query and hash state.
- Lane reconciliation retains completed lanes, falls back to the lowest active lane, and clears on an empty set.
- Replay keys ignore native controls, summaries, tabs and the move log region. The move log stops propagation on its own cells.
- Focus restoration returns to the originating row or heading, and the initial direct-link render does not move focus.
- No injection or XSS surface in the new templates. All interpolations are text or attribute bindings with numeric style values validated.

**Behavioural change, not a defect.** `keisei/showcase/inference.py:329` now rejects scalar scores outside the unit range, and the runner marks such a game abandoned. Previously the value was displayed. Tests show this is intentional.

## Checks not run

I executed no tests, builds, browsers or screen readers. The 452 frontend tests, the Python suites, the seven CI jobs and the Playwright evidence are parent-reported. Screen-reader validation remains the authorised Unable to test item under the existing follow-up task. No tracker state was written.
