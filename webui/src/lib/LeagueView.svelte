<script>
  import { leagueStats, learnerEntry, tournamentStats, displayElo, leagueCapacity } from '../stores/league.js'
  import LeagueTable from './LeagueTable.svelte'
  import MatchupMatrix from './MatchupMatrix.svelte'
  import RecentMatches from './RecentMatches.svelte'
  import LeagueEventLog from './LeagueEventLog.svelte'
  import EntryDetail from './EntryDetail.svelte'
  import HistoricalLibrary from './HistoricalLibrary.svelte'
  import { focusedEntryId } from '../stores/league.js'
  import { tick } from 'svelte'

  $: stats = $leagueStats
  $: tStats = $tournamentStats
  $: learner = $learnerEntry
  $: learnerName = learner?.display_name || null

  let entryDetailHeading

  function closeDetail() { focusedEntryId.set(null) }
  function handleMainKeydown(e) {
    if (e.key === 'Escape' && $focusedEntryId != null) {
      e.preventDefault()
      closeDetail()
    }
  }

  // Focus EntryDetail heading only when focusedEntryId actually changes value
  let prevFocusedId = null
  $: {
    const currentId = $focusedEntryId
    if (currentId !== prevFocusedId) {
      prevFocusedId = currentId
      if (currentId != null) {
        tick().then(() => entryDetailHeading?.focus())
      }
    }
  }
</script>

<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<!-- Esc-to-close-detail handler — needs to be on the focused main region so it
     only fires while the user is engaged with the league view, not globally. -->
<main id="league-main" class="league-view" aria-labelledby="tab-league" tabindex="-1" on:keydown={handleMainKeydown}>
  {#if stats}
    <div class="stats-banner" role="region" aria-label="League summary">
      <div class="stat-card highlight">
        <span class="stat-value">{stats.topEntry?.display_name || stats.topEntry?.architecture || '—'}</span>
        <span class="stat-label">Top Rated · {Math.round(stats.topEntry ? displayElo(stats.topEntry).value : 0)}</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{stats.poolSize} / {$leagueCapacity.total}</span>
        <span class="stat-label">Pool Size</span>
      </div>
      <div class="stat-card stat-trio">
        <div class="trio-item">
          <span class="stat-value">{stats.totalRounds ?? '—'}</span>
          <span class="stat-label">Rounds</span>
        </div>
        <span class="trio-sep" aria-hidden="true"></span>
        <div class="trio-item">
          <span class="stat-value">{stats.totalMatches ?? '—'}</span>
          <span class="stat-label">Matches</span>
        </div>
        <span class="trio-sep" aria-hidden="true"></span>
        <div class="trio-item">
          <span class="stat-value">{stats.totalGames ?? '—'}</span>
          <span class="stat-label">Games</span>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-value">{stats.eloMin ?? '—'} – {stats.eloMax ?? '—'}</span>
        <span class="stat-label">Composite Elo · {stats.eloSpread ?? '—'} spread</span>
      </div>
      {#if tStats}
        <div class="stat-card completed-round">
          <span class="stat-label">Last completed round</span>
          <span class="stat-value">{Math.round(tStats.games_per_min)} <span class="round-unit">games/min</span></span>
          <span class="stat-label">Capacity · {tStats.active_slots} concurrent slots</span>
          {#if tStats.pairings_completed != null && tStats.pairings_requested != null}
            <span class="stat-label">{tStats.pairings_completed}/{tStats.pairings_requested} pairings completed</span>
          {/if}
          {#if tStats.updated_at}
            <time datetime={tStats.updated_at}>{new Date(tStats.updated_at).toLocaleString()}</time>
          {/if}
        </div>
      {/if}
    </div>
  {/if}

  <div class="league-grid" class:has-detail={$focusedEntryId != null}>
    <div class="left-col">
      <div class="table-wrapper">
        <LeagueTable totalSlots={$leagueCapacity.total} roleCapacities={$leagueCapacity.roles} />
      </div>
      <section class="historical-library-wrapper" aria-label="Historical benchmarks">
        <HistoricalLibrary />
      </section>
      {#if $focusedEntryId != null}
        <div class="entry-detail-wrapper" role="region" aria-label="Entry detail">
          <div class="detail-close-anchor">
            <button class="detail-close-btn" on:click={closeDetail} aria-label="Close entry detail">✕</button>
          </div>
          <EntryDetail entryId={$focusedEntryId} bind:headingEl={entryDetailHeading} />
        </div>
      {/if}
    </div>
    <div class="right-col">
      <MatchupMatrix {learnerName} totalSlots={$leagueCapacity.total} />
    </div>
    <div class="bottom-right-split">
      <div class="event-log-wrapper">
        <LeagueEventLog />
      </div>
      <div class="recent-matches-wrapper">
        <RecentMatches />
      </div>
    </div>
  </div>
</main>

<style>
  .league-view {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px 16px;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }
  .league-view:focus { outline: none; }

  .stats-banner {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    flex-shrink: 0;
  }

  .stat-card {
    flex: 1;
    min-width: 150px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 14px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .stat-card.highlight {
    flex: 1.5;
    border-color: var(--accent-gold);
    background: rgba(200, 150, 46, 0.06);
  }

  .stat-card.completed-round {
    border-color: var(--accent-teal);
  }
  .completed-round time { font-size: 11px; color: var(--text-muted); }

  .round-unit {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
  }

  .stat-value {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    font-family: monospace;
  }

  .stat-card.highlight .stat-value {
    color: var(--accent-gold);
  }

  .stat-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stat-trio {
    flex-direction: row;
    justify-content: center;
    gap: 0;
    padding: 10px 8px;
  }

  .trio-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .trio-sep {
    width: 1px;
    align-self: stretch;
    margin: 4px 0;
    background: var(--border);
  }

  /* --- Main grid: 2 columns, 2 rows. The 21×21 head-to-head matrix needs
     more horizontal room than the 11-column leaderboard, so the right column
     gets the larger share. --- */
  .league-grid {
    display: grid;
    grid-template-columns: 2fr 3fr;
    grid-template-rows: 3fr 1fr;
    gap: 12px;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  /* Left column: table + optional detail. Spans both rows so the leaderboard
     extends down to where the event log used to live. */
  .left-col {
    grid-column: 1;
    grid-row: 1 / span 2;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 0;
    overflow: hidden;
  }

  .table-wrapper {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .historical-library-wrapper {
    flex: 0 1 auto;
    max-height: 35%;
    min-height: 100px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-secondary);
  }

  /* When detail is open, table shrinks to share space */
  .has-detail .table-wrapper {
    flex: 1;
    min-height: 180px;
  }

  .entry-detail-wrapper {
    flex: 0 1 auto;
    min-height: 120px;
    max-height: 60%;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-secondary);
    position: relative;
  }

  /* Sticky anchor row: zero-height container that pins to the top of the
     scrolling wrapper, allowing the close button to float in the top-right
     corner while EntryDetail content scrolls underneath. */
  .detail-close-anchor {
    position: sticky;
    top: 0;
    height: 0;
    z-index: 2;
    display: flex;
    justify-content: flex-end;
    pointer-events: none;
  }

  .detail-close-btn {
    pointer-events: auto;
    margin: 4px 4px 0 0;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-secondary);
    cursor: pointer;
    min-width: 44px;
    min-height: 44px;
    padding: 2px 4px;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .detail-close-btn:hover {
    color: var(--text-primary);
    border-color: var(--text-secondary);
    background: var(--bg-card);
  }

  .detail-close-btn:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  /* Right column: matchup matrix, always visible */
  .right-col {
    grid-column: 2;
    grid-row: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* Bottom-right cell: 50/50 split between event log and recent matches. */
  .bottom-right-split {
    grid-column: 2;
    grid-row: 2;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    min-height: 0;
    overflow: hidden;
  }

  .recent-matches-wrapper,
  .event-log-wrapper {
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .recent-matches-wrapper {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  @media (max-width: 1200px) {
    .league-view { height: auto; overflow-y: auto; }
    .league-grid {
      flex: none;
      height: auto;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto auto auto;
      overflow: visible;
    }
    .league-grid > *, .left-col > *, .bottom-right-split > * { min-width: 0; }

    .left-col {
      grid-column: 1;
      grid-row: 1;
      overflow: visible;
    }
    .table-wrapper, .has-detail .table-wrapper {
      flex: none;
      min-height: 260px;
      max-height: 60vh;
      overflow: auto;
    }
    .historical-library-wrapper { flex: none; max-height: 50vh; }
    .right-col {
      grid-column: 1;
      grid-row: 2;
      overflow: visible;
    }
    .bottom-right-split {
      grid-column: 1;
      grid-row: 3;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto auto;
    }
  }

  @media (max-width: 600px) {
    .league-view { padding: 10px; }
    .stat-card, .stat-card.highlight { flex: 1 1 100%; min-width: 0; }
    .stats-banner { gap: 8px; }
    .league-grid, .bottom-right-split { overflow: visible; }
  }
</style>
