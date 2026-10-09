<script>
  import { leagueRanked, leagueEntries, focusedEntryId, headToHead } from '../stores/league.js'
  import { getRoleIcon } from './roleIcons.js'
  import { matchupIdentity, matchupRows } from './matchupRows.js'

  let selectedPlayer = ''
  let showRecordList = false

  /** Current learner display_name — used to build an aggregate "Trainer" row */
  export let learnerName = null
  /** Total grid size — pad with placeholders to fill */
  export let totalSlots = 20

  $: focused = $focusedEntryId

  // Entries sorted by Elo descending (same as leaderboard)
  $: entries = $leagueRanked

  // Build aggregated trainer record across all its snapshots
  $: trainerSnapshotIds = learnerName
    ? new Set($leagueEntries.filter(e => e.display_name === learnerName).map(e => e.id))
    : new Set()

  $: hasTrainerRow = learnerName && trainerSnapshotIds.size > 0

  // Matrix participants: all entries + optionally a synthetic trainer row
  // The trainer row id is 'trainer' (string, won't collide with numeric ids)
  $: participants = (() => {
    const p = entries.map(e => ({
      ...e,
      id: e.id,
      label: e.display_name || e.architecture,
      shortLabel: getRoleIcon(e.role) + ' ' + shortName(e.display_name || e.architecture),
      isTrainer: false,
    }))
    if (hasTrainerRow) {
      p.unshift({
        id: 'trainer',
        label: learnerName + ' · Trainer aggregate (all snapshots)',
        shortLabel: shortName(learnerName) + '*',
        isTrainer: true,
      })
    }
    while (p.length < totalSlots) {
      const slot = p.length + 1
      p.push({
        id: `empty-${slot}`,
        label: `Slot ${slot}`,
        shortLabel: `#${slot}`,
        isTrainer: false,
        isPlaceholder: true,
      })
    }
    return p
  })()

  function shortName(name) {
    if (!name) return '?'
    // Truncate long names
    return name.length > 12 ? name.slice(0, 11) + '…' : name
  }

  // Build h2h map from pre-aggregated backend data + trainer aggregation
  // Uses headToHead store for individual entry pairs, then adds trainer synthetic row
  $: h2h = (() => {
    // Start with a copy of the pre-aggregated headToHead data
    const map = new Map($headToHead)

    // Add trainer aggregation: sum all trainer snapshot h2h vs non-trainer entries
    if (hasTrainerRow) {
      // Collect all opponent IDs that trainer snapshots have played against
      const opponentIds = new Set()
      for (const [key] of map) {
        const [aStr, bStr] = key.split('-')
        const a = Number(aStr), b = Number(bStr)
        if (trainerSnapshotIds.has(a) && !trainerSnapshotIds.has(b)) opponentIds.add(b)
        if (trainerSnapshotIds.has(b) && !trainerSnapshotIds.has(a)) opponentIds.add(a)
      }

      // Aggregate trainer vs each opponent
      for (const oppId of opponentIds) {
        let w = 0, l = 0, d = 0
        for (const trainerId of trainerSnapshotIds) {
          const rec = map.get(`${trainerId}-${oppId}`)
          if (rec) { w += rec.w; l += rec.l; d += rec.d }
        }
        if (w + l + d > 0) {
          const total = w + l + d
          map.set(`trainer-${oppId}`, { w, l, d, total, winRate: w / total })
          map.set(`${oppId}-trainer`, { w: l, l: w, d, total, winRate: l / total })
        }
      }
    }

    return map
  })()

  function cellData(rowId, colId) {
    if (rowId === colId) return null
    // Skip trainer vs its own snapshots
    if (rowId === 'trainer' && trainerSnapshotIds.has(colId)) return null
    if (colId === 'trainer' && trainerSnapshotIds.has(rowId)) return null
    return h2h.get(`${rowId}-${colId}`) || null
  }

  let rows = []
  let hasAnyRecords = false
  $: {
    // cellData closes over both stores; declare those reactive dependencies.
    h2h; trainerSnapshotIds
    rows = matchupRows(participants, cellData, selectedPlayer)
    hasAnyRecords = matchupRows(participants, cellData).length > 0
  }
  $: if (selectedPlayer && !participants.some(p => String(p.id) === selectedPlayer)) selectedPlayer = ''

  function cellColor(winRate) {
    if (winRate == null) return 'transparent'
    // Red (0%) → neutral (50%) → green (100%)
    if (winRate >= 0.5) {
      const t = (winRate - 0.5) * 2 // 0..1
      return `rgba(77, 184, 168, ${0.08 + t * 0.35})`
    } else {
      const t = (0.5 - winRate) * 2 // 0..1
      return `rgba(224, 80, 80, ${0.08 + t * 0.35})`
    }
  }

  function formatRate(winRate) {
    if (winRate == null) return ''
    return Math.round(winRate * 100) + '%'
  }
</script>

<div class="matrix-card">
  <h2 class="section-header">Head-to-Head</h2>

  <label class="player-filter">Player
    <select bind:value={selectedPlayer}>
      <option value="">All players</option>
      {#each participants.filter(p => !p.isPlaceholder) as player}
        <option value={String(player.id)}>{matchupIdentity(player)}</option>
      {/each}
    </select>
  </label>
  <button class="list-toggle" aria-expanded={showRecordList} aria-controls="matchup-records" on:click={() => showRecordList = !showRecordList}>
    {showRecordList ? 'Hide' : 'Show'} matchup record list
  </button>
  <div id="matchup-records" class="h2h-list-view" class:expanded={showRecordList || selectedPlayer !== '' || !hasAnyRecords}>
    {#if !hasAnyRecords}
      <p class="empty">No matchup data yet.</p>
    {:else if rows.length === 0}
      <p class="empty">No games for this player filter.</p>
    {:else}
      <p class="record-help">Each pair appears once. Wins and losses are from the first named player's perspective. Trainer aggregates are separate from individual snapshots.</p>
      <ul class="record-list">
        {#each rows as row}
          <li class="h2h-item" class:aggregate={row.player.isTrainer || row.opponent.isTrainer}>
            <span class="h2h-names">{matchupIdentity(row.player)} <span class="versus">vs</span> {matchupIdentity(row.opponent)}</span>
            <span class="perspective">Record from {matchupIdentity(row.player)} perspective</span>
            <span class="h2h-record">{row.w} wins · {row.l} losses · {row.d} draws · {row.total} games</span>
            <span class="h2h-rate">{formatRate(row.winRate)} wins</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <!-- Desktop matrix view -->
  <div class="matrix-desktop" class:filtered={selectedPlayer !== ''}>
  <div class="matrix-legend" aria-label="Color legend">
    <span class="legend-swatch" style="background: rgba(224, 80, 80, 0.35)"></span>
    <span class="legend-label">0%</span>
    <span class="legend-swatch" style="background: rgba(224, 80, 80, 0.22)"></span>
    <span class="legend-swatch" style="background: transparent; border: 1px solid var(--border-subtle)"></span>
    <span class="legend-label">50%</span>
    <span class="legend-swatch" style="background: rgba(77, 184, 168, 0.22)"></span>
    <span class="legend-swatch" style="background: rgba(77, 184, 168, 0.43)"></span>
    <span class="legend-label">100%</span>
  </div>
    <!-- svelte-ignore a11y-no-noninteractive-tabindex -->
    <div class="matrix-scroll" role="region" aria-label="Scrollable comparison matrix" tabindex="0">
      <table class="matrix" aria-label="Head-to-head win rate matrix">
        <thead>
          <tr>
            <th class="corner" scope="col"></th>
            {#each participants as col}
              <th class="col-header" class:hl={focused != null && col.id === focused} class:placeholder={col.isPlaceholder} aria-label={matchupIdentity(col)} title={matchupIdentity(col)} scope="col">
                <span class="rotated">{col.shortLabel}</span>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each participants as row}
            <tr class:hl-row={focused != null && row.id === focused}>
              <th class="row-header" class:trainer-row={row.isTrainer} class:hl={focused != null && row.id === focused} class:placeholder={row.isPlaceholder} aria-label={matchupIdentity(row)} title={matchupIdentity(row)} scope="row">{row.shortLabel}</th>
              {#each participants as col}
                {#if row.id === col.id}
                  <td class="self-cell" class:hl={focused != null && (row.id === focused || col.id === focused)}>—</td>
                {:else if cellData(row.id, col.id) === null}
                  <td class="no-data" class:hl={focused != null && (row.id === focused || col.id === focused)}>·</td>
                {:else}
                  <td
                    class="rate-cell"
                    class:hl={focused != null && (row.id === focused || col.id === focused)}
                    style="background: {cellColor(cellData(row.id, col.id).winRate)}"
                    title="{matchupIdentity(row)} vs {matchupIdentity(col)}: {cellData(row.id, col.id).w}W {cellData(row.id, col.id).l}L {cellData(row.id, col.id).d}D ({cellData(row.id, col.id).total} games)"
                    aria-label="{matchupIdentity(row)} vs {matchupIdentity(col)}: {formatRate(cellData(row.id, col.id).winRate)} win rate, {cellData(row.id, col.id).w} wins, {cellData(row.id, col.id).l} losses, {cellData(row.id, col.id).d} draws"
                  >
                    {formatRate(cellData(row.id, col.id).winRate)}
                  </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
</div>

<style>
  .matrix-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .matrix-scroll {
    overflow: auto;
    min-height: 0;
    flex: 1;
    display: flex;
    align-items: flex-start;
    justify-content: flex-start;
  }

  .matrix {
    margin-inline: auto;
    border-collapse: collapse;
    font-size: 15px;
    white-space: nowrap;
  }

  .corner {
    min-width: 92px;
  }

  .col-header {
    padding: 3px 6px;
    vertical-align: bottom;
  }

  .rotated {
    display: block;
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .row-header {
    text-align: right;
    padding: 6px 10px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-muted);
    max-width: 115px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row-header.trainer-row {
    color: var(--accent-teal);
    font-weight: 700;
  }

  td {
    text-align: center;
    padding: 6px 8px;
    min-width: 50px;
    font-family: monospace;
    font-size: 14px;
    font-weight: 600;
    border: 1px solid var(--border-subtle);
    color: var(--text-primary);
  }

  .self-cell {
    background: var(--bg-primary);
    color: var(--text-muted);
  }

  .no-data {
    color: var(--text-muted);
    font-size: 12px;
  }

  .rate-cell {
    cursor: help;
    transition: opacity 0.1s;
  }

  .rate-cell:hover {
    opacity: 0.8;
  }

  /* Faint crosshatch highlight for focused entry's row + column */
  .hl {
    background-image: repeating-linear-gradient(
      45deg,
      transparent,
      transparent 3px,
      rgba(77, 184, 168, 0.08) 3px,
      rgba(77, 184, 168, 0.08) 4px
    );
  }

  th.hl {
    color: var(--accent-teal);
  }

  .placeholder {
    color: var(--text-muted);
    opacity: 0.35;
  }

  .empty {
    color: var(--text-muted);
    font-size: 13px;
    text-align: center;
    padding: 24px;
  }

  /* Mobile list view: shown below 768px, hidden on desktop */
  .h2h-list-view {
    display: none;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }

  .h2h-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    font-size: 12px;
    border-radius: 3px;
  }

  .h2h-item:hover { background: var(--bg-card); }

  .h2h-names {
    flex: 1;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .h2h-record {
    font-family: monospace;
    font-size: 12px;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .h2h-rate {
    font-family: monospace;
    font-size: 12px;
    font-weight: 600;
    flex-shrink: 0;
    min-width: 36px;
    text-align: right;
  }

  .matrix-desktop { display: contents; }

  @media (max-width: 768px) {
    .h2h-list-view { display: flex; }
    .matrix-desktop { display: none; }
  }

  @media (prefers-reduced-motion: reduce) {
    .rate-cell { transition: none; }
  }

  .matrix-legend {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-bottom: 8px;
    flex-shrink: 0;
  }

  .legend-swatch {
    width: 16px;
    height: 10px;
    border-radius: 2px;
    display: inline-block;
  }

  .legend-label {
    font-size: 12px;
    color: var(--text-muted);
    font-family: monospace;
  }

  .rate-cell:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: -2px;
  }
  .player-filter { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; font-size: 13px; }
  select { min-height: 44px; min-width: 0; width: 100%; color: var(--text-primary); background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; padding: 8px; }
  .list-toggle { align-self: flex-start; min-height: 44px; margin-bottom: 8px; padding: 8px 12px; color: var(--text-primary); background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
  .h2h-list-view.expanded { display: flex; flex: none; max-height: 48vh; }
  .matrix-desktop.filtered { display: none; }
  .record-list { padding: 0; margin: 0; list-style: none; }
  .record-help { font-size: 12px; color: var(--text-muted); margin: 0 0 8px; }
  .h2h-item { display: grid; gap: 4px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
  .h2h-names { white-space: normal; overflow: visible; overflow-wrap: anywhere; }
  .perspective { font-size: 12px; color: var(--text-muted); overflow-wrap: anywhere; }
  .h2h-rate { text-align: left; color: var(--text-primary); }
  .aggregate { border-left: 3px solid var(--accent-gold); padding-left: 8px; }
  .versus { color: var(--text-muted); }
  @media (max-width: 768px) {
    .list-toggle { display: none; }
    .h2h-list-view, .h2h-list-view.expanded { display: flex; overflow: visible; max-height: none; }
    .matrix-card { overflow: visible; }
  }
</style>
