<script>
  import { showcaseGame, showcaseQueue, queueDepth, sidecarAlive } from '../stores/showcase.js'

  // The banner is intentionally minimal — three glanceable cards:
  //  1. Engine status (live alive dot)
  //  2. Active match ply count
  //  3. Queue depth (pending matches)
  //
  // We deliberately do NOT compute "matches today" or "avg game length" here:
  // those need backend aggregates that don't exist yet. When they do, add a
  // fourth card. Surfacing zero/unknown values would just be noise.
  $: livePly = $showcaseGame?.total_ply ?? 0
  $: matchActive = $showcaseGame != null && $showcaseGame.status === 'in_progress'
  $: pending = $queueDepth
</script>

<section class="stats-banner" aria-label="Showcase summary">
  <!--
    Engine status here is a passive indicator; the urgent "engine is offline"
    callout (role=alert) lives in ShowcaseView so screen readers don't get
    duplicate announcements. We still tint the dot for sighted users.
  -->
  <div class="stat-card" class:alive={$sidecarAlive} class:offline={!$sidecarAlive}>
    <span class="stat-value">
      <span class="dot" aria-hidden="true"></span>
      {$sidecarAlive ? 'Online' : 'Offline'}
    </span>
    <span class="stat-label">Showcase Engine</span>
  </div>
  <div class="stat-card" class:highlight={matchActive}>
    <span class="stat-value">
      {#if matchActive}
        Ply {livePly}
      {:else}
        —
      {/if}
    </span>
    <span class="stat-label">
      {#if matchActive}
        Live Match
      {:else}
        No Active Match
      {/if}
    </span>
  </div>
  <div class="stat-card" class:warn={pending >= 5}>
    <span class="stat-value">{pending}</span>
    <span class="stat-label">
      {#if pending >= 5}
        Queue Full
      {:else}
        Pending in Queue
      {/if}
    </span>
  </div>
</section>

<style>
  .stats-banner { display:flex; gap:8px 24px; padding:6px 12px; flex-wrap:wrap; border-bottom:1px solid var(--border); font-size:12px; }
  .stat-card { display:flex; gap:6px; align-items:center; }
  .stat-value { font-weight:700; color:var(--accent-teal); }
  .stat-label { color:var(--text-secondary); }
  .offline .stat-value { color:var(--text-muted); }
  .warn .stat-value { color:var(--accent-gold); }
  .dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:currentColor; }
</style>
