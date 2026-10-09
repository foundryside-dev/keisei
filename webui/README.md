# Keisei Spectator Dashboard

Svelte SPA for watching Shogi training in real time.

## Development

```bash
# Terminal 1: Start training (populates SQLite)
uv run keisei-train --config keisei.toml --epochs 100 --steps-per-epoch 64

# Terminal 2: Start API server
uv run keisei-serve --config keisei.toml

# Terminal 3: Start Svelte dev server (proxies /ws and /api to FastAPI)
cd webui && npm run dev
# Open http://localhost:5173
```

## Production Build

```bash
cd webui && npm run build
# Output: keisei/server/static/
# Then just run: uv run keisei-serve --config keisei.toml
# Open http://localhost:8000
```

## Watching and sharing

Training keeps the chosen live lane on completion. A replacement game in that
lane advances the board; a removed lane falls back to the lowest active lane.
Choose game lists every loaded lane. Run details, Player details and Training
metrics open on demand.

Watch match follows the latest match unless you select a saved identity. Pausing
or selecting any move pins that stored position, including the current tail.
Resume following / End follows the same match; Watch latest match follows new
match identities. Focus the replay viewer to use arrows (Shift = five moves),
Home, End, Space and H. Native controls keep their own keyboard behavior.
Position as text includes occupied squares, promotion, hands and side to move;
move announcements are opt-in.

Shareable links use the root path, so they also reload against the production
FastAPI static server:

- `/?view=league&entry=42`
- `/?view=showcase&match=123&ply=17`
- `/?view=showcase&match=123` follows that match's tail.
- `/?view=showcase` follows the latest match.
- `/?view=about#about-big-idea`

`ply` is an actual persisted ply, not an array index. Invalid/missing matches
show recovery actions; out-of-range numeric positions show a clamp explanation.
Explicit links take precedence over a remembered view. User navigation creates
browser history; scrubbing replaces the current entry. Copy link saves the
currently displayed match/position without changing following mode.

The read-only APIs are `GET /api/showcase/games/{id}` (at most 2048 stored moves;
413 for larger legacy/corrupt records) and
`GET /api/league/gauntlet?before_epoch=E&limit=5` (1–50 complete epochs per page).
Schema v9 adds nullable `evaluation_json`; old moves remain replayable. Estimates
are uncalibrated model outcome scores: scalar `(v+1)/2`, WDL `P(win)+P(draw)/2`,
converted once to Black's perspective and labelled for the pre-move position.
Older/invalid data is shown as unavailable. Back up production databases before
schema upgrades; rollback to an older schema version requires a compatible
backup or forward fix.
