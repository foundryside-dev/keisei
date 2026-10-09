<script>
  import { historicalLibrary, gauntletResults } from '../stores/league.js'
  import { trainingState } from '../stores/training.js'
  import { gauntletHistory } from '../stores/gauntletHistory.js'
  import { onMount } from 'svelte'

  $: {
    gauntletHistory.setContext($trainingState?.started_at ?? null)
    gauntletHistory.setLive($gauntletResults)
  }
  $: gauntletByEpoch = $gauntletHistory.epochs
  onMount(() => { if (!gauntletByEpoch.length) gauntletHistory.loadOlder() })

  $: currentEpoch = $trainingState?.current_epoch || 0
  $: maxGauntletEpoch = $gauntletResults.length > 0
    ? Math.max(...$gauntletResults.map(g => g.epoch))
    : null
  $: staleness = maxGauntletEpoch != null && currentEpoch > 0
    ? currentEpoch - maxGauntletEpoch
    : null

</script>

<div class="historical-library">
  <div class="slots-section">
    <h4 class="section-label">
      Library Slots
      {#if staleness != null}
        <span class="staleness">Last gauntlet: {staleness} epoch{staleness !== 1 ? 's' : ''} ago</span>
      {/if}
    </h4>
    {#if $historicalLibrary.length === 0}
      <p class="empty">No historical slots configured</p>
    {:else}
      <table>
        <caption class="sr-only">Historical library slot assignments</caption>
        <thead>
          <tr>
            <th scope="col" class="num">#</th>
            <th scope="col">Entry</th>
            <th scope="col" class="num">Target</th>
            <th scope="col" class="num">Actual</th>
            <th scope="col">Mode</th>
          </tr>
        </thead>
        <tbody>
          {#each $historicalLibrary as slot}
            <tr>
              <td class="num">{slot.slot_index}</td>
              <td>{slot.entry_name || '—'}</td>
              <td class="num">{slot.target_epoch}</td>
              <td class="num">{slot.actual_epoch ?? '—'}</td>
              <td class="mode">{slot.selection_mode}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>

    <div class="gauntlet-section">
      <h4 class="section-label">{gauntletByEpoch.length <= 5 ? 'Latest 5 evaluations' : `Evaluations · ${gauntletByEpoch.length} epochs loaded`}</h4>
      {#if !gauntletByEpoch.length && !$gauntletHistory.loading}<p class="empty">No evaluation results yet.</p>{/if}
      {#each gauntletByEpoch as [epoch, results] (epoch)}
        <div class="gauntlet-epoch">
          <span class="epoch-header">Epoch {epoch}</span>
          {#each results as g (g.id)}
            <div class="gauntlet-row">
              <span class="slot-tag">Slot {g.historical_slot}</span>
              <span class="wld">{g.wins}W {g.losses}L {g.draws}D</span>
              {#if g.elo_before != null && g.elo_after != null}
                {@const delta = Math.round(g.elo_after - g.elo_before)}
                <span class="elo-delta" class:positive={delta > 0} class:negative={delta < 0}>
                  {delta > 0 ? '+' : ''}{delta}
                </span>
              {/if}
            </div>
          {/each}
        </div>
      {/each}
      {#if $gauntletHistory.error}
        <p role="alert" class="history-status">{$gauntletHistory.error}</p>
      {/if}
      {#if $gauntletHistory.hasMore}
        <button class="load-history" disabled={$gauntletHistory.loading} on:click={() => gauntletHistory.loadOlder()}>
          {$gauntletHistory.loading ? 'Loading evaluations…' : $gauntletHistory.error ? 'Retry loading older evaluations' : 'Load 5 older evaluations'}
        </button>
      {:else if gauntletByEpoch.length}
        <p class="history-status">End of evaluation history.</p>
      {/if}
      <p class="sr-only" role="status">{$gauntletHistory.loading ? 'Loading older evaluations' : `${gauntletByEpoch.length} evaluation epochs loaded`}</p>
    </div>
</div>

<style>
  .historical-library { padding: 10px 14px; display: flex; flex-direction: column; gap: 12px; }
  .section-label {
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--text-muted); margin: 0 0 6px;
    display: flex; align-items: center; gap: 8px;
  }
  .staleness { font-weight: 400; font-size: 12px; color: var(--accent-gold); text-transform: none; letter-spacing: 0; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  thead { color: var(--text-muted); font-size: 12px; }
  th, td { text-align: left; padding: 3px 8px; }
  th.num, td.num { text-align: right; }
  .mode { font-size: 12px; color: var(--text-muted); }
  .gauntlet-epoch { margin-bottom: 6px; }
  .epoch-header {
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--text-muted); display: block; margin-bottom: 2px;
  }
  .gauntlet-row {
    display: flex; align-items: center; gap: 8px; font-size: 12px;
    padding: 2px 4px; border-radius: 3px;
  }
  .gauntlet-row:hover { background: var(--bg-card); }
  .slot-tag { font-size: 12px; color: var(--text-muted); min-width: 48px; }
  .wld { font-family: monospace; font-size: 12px; color: var(--text-secondary); }
  .elo-delta { font-family: monospace; font-size: 12px; font-weight: 600; }
  .elo-delta.positive { color: var(--accent-teal); }
  .elo-delta.negative { color: var(--danger); }
  .empty { color: var(--text-muted); font-size: 12px; text-align: center; padding: 12px; }
  .load-history { min-height: 44px; padding: 8px 12px; color: var(--text-primary); background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
  .load-history:disabled { cursor: wait; }
  .history-status { font-size: 12px; color: var(--text-muted); }
  td { overflow-wrap: anywhere; }
  @media (max-width: 600px) { .historical-library { padding: 10px; } th, td { padding: 4px; } .section-label { flex-wrap: wrap; } }
</style>
