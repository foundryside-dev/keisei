<script>
  import { leagueEntries, headToHead, displayElo } from '../stores/league.js'
  import { getRoleInfo } from './roleIcons.js'

  /** Showcase game payload from backend (showcase_games row + queue context). */
  export let game
  /** The move currently being displayed (live tail OR scrubbed-to ply). */
  export let displayedMove = null
  /** True when user is scrubbing through history rather than watching live. */
  export let scrubbing = false
  /** Estimated typical game length in plies, used for the progress bar. */
  export let estimatedTotalPly = 140

  // Lookup the league entries by entry_id so we can decorate each player with
  // tier badge and architecture. entry_id_black/white are TEXT in the DB so
  // we string-coerce both sides of the comparison.
  $: entryById = (() => {
    const map = new Map()
    for (const e of $leagueEntries) map.set(String(e.id), e)
    return map
  })()
  $: blackEntry = game ? entryById.get(String(game.entry_id_black)) : null
  $: whiteEntry = game ? entryById.get(String(game.entry_id_white)) : null

  $: blackRole = blackEntry ? getRoleInfo(blackEntry.role, blackEntry.status) : null
  $: whiteRole = whiteEntry ? getRoleInfo(whiteEntry.role, whiteEntry.status) : null

  $: blackArchSummary = archSummary(blackEntry)
  $: whiteArchSummary = archSummary(whiteEntry)

  function archSummary(entry) {
    if (!entry) return null
    const mp = entry.model_params || {}
    const parts = []
    if (mp.num_blocks && mp.channels) parts.push(`b${mp.num_blocks}c${mp.channels}`)
    if (mp.se_reduction) parts.push(`SE-${mp.se_reduction}`)
    return { arch: entry.architecture || '', topology: parts.join(' · ') }
  }

  // Use display ELO when available (handles tier-specific ratings); fall back
  // to the snapshot ELO captured on the showcase game row.
  $: blackElo = blackEntry ? Math.round(displayElo(blackEntry).value) : (game?.elo_black != null ? Math.round(game.elo_black) : null)
  $: whiteElo = whiteEntry ? Math.round(displayElo(whiteEntry).value) : (game?.elo_white != null ? Math.round(game.elo_white) : null)

  // Head-to-head for these two players (canonical key built by store).
  $: h2h = (() => {
    if (!blackEntry || !whiteEntry) return null
    const key = `${blackEntry.id}-${whiteEntry.id}`
    return $headToHead.get(key) || null
  })()

  // Whose turn it is, derived from displayed move (the side-to-move *after*
  // that move was played).
  $: turn = displayedMove?.current_player || 'black'
  $: liveTotalPly = game?.total_ply ?? 0
  $: viewedPly = displayedMove?.ply ?? liveTotalPly
  $: progressPct = Math.min(100, (liveTotalPly / Math.max(estimatedTotalPly, 1)) * 100)

  $: isFinished = game?.status && game.status !== 'in_progress'
  $: resultLabel = isFinished ? game.status.replaceAll('_', ' ') : null
</script>

<section class="scorecard" aria-label="Match scorecard">
  {#each [{side:'Black',name:game?.name_black,role:blackRole,arch:blackArchSummary,elo:blackElo},{side:'White',name:game?.name_white,role:whiteRole,arch:whiteArchSummary,elo:whiteElo}] as player}
    <details class="player" class:active-turn={!isFinished && turn === player.side.toLowerCase()}>
      <summary aria-label={`Player details: ${player.side}, ${player.name || 'Unknown'}`}>
        <span class="side">{player.side}</span>
        <span class="name">{player.name || '—'}</span>
        {#if player.role}<span class="tier">{player.role.label}</span>{/if}
        {#if player.elo != null}<span class="elo">{player.elo}</span>{/if}
        <span class="details-hint">Player details</span>
      </summary>
      <p>Architecture: {player.arch?.arch || 'Unavailable'}{#if player.arch?.topology} · {player.arch.topology}{/if}</p>
    </details>
  {/each}
  <div class="footer-strip">
    {#if isFinished}<span class="result" role="status">{resultLabel}</span>{/if}
    <span>Ply {viewedPly}{#if scrubbing} / latest {liveTotalPly}{/if}{#if !isFinished} · {turn} to move{/if}</span>
    {#if h2h?.total > 0}<span>Black head-to-head: {h2h.w} wins, {h2h.l} losses, {h2h.d} draws</span>{/if}
  </div>
</section>

<style>
  .scorecard { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-bottom:1px solid var(--border); }
  .player { background:var(--bg-secondary); min-width:0; }
  .player.active-turn { box-shadow:inset 3px 0 0 var(--accent-teal); }
  summary { display:flex; align-items:center; gap:6px 10px; flex-wrap:wrap; min-height:44px; padding:6px 12px; cursor:pointer; font-size:13px; }
  .name { overflow-wrap:anywhere; font-weight:600; min-width:0; flex:1; }
  .side,.tier,.details-hint { color:var(--text-secondary); font-size:12px; }
  .elo { color:var(--accent-teal); font-weight:700; }
  p { padding:8px 12px; font-size:13px; overflow-wrap:anywhere; }
  .footer-strip { grid-column:1/-1; display:flex; flex-wrap:wrap; gap:8px 24px; font-size:12px; color:var(--text-secondary); padding:4px 12px; }
  .result { color:var(--accent-teal); }
  @media(max-width:600px) { summary { padding:6px 8px; gap:4px 8px; } .name { flex-basis:100%; order:1; } .details-hint { order:2; } }
</style>
