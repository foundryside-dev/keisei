<script>
  import { onDestroy } from 'svelte'
  import { trainingState, trainingAlive } from '../stores/training.js'
  import { connectionState } from './ws.js'
  import { getIndicator } from './indicator.js'
  import { buildConfigTooltip } from './configTooltip.js'
  import { parseUTC, formatElapsed } from './timeFormat.js'
  import TabBar from './TabBar.svelte'

  $: status = $trainingState?.status || 'unknown'
  $: epoch = $trainingState?.current_epoch || 0
  $: step = $trainingState?.current_step || 0
  $: alive = $trainingAlive
  $: displayName = $trainingState?.display_name || 'Player'
  $: modelArch = $trainingState?.model_arch || ''
  $: stats = $trainingState?.system_stats || {}
  $: gpus = stats.gpus || []

  $: totalEpochs = $trainingState?.total_epochs || null
  $: phase = $trainingState?.phase || ''
  $: indicator = getIndicator(alive, status)

  $: configTooltip = buildConfigTooltip($trainingState?.config_json, modelArch)

  // Wall clock: real time since training started (ticks every second)
  // Train clock: time the trainer has been active (heartbeat_at - started_at, freezes when stopped)

  $: startedAt = parseUTC($trainingState?.started_at)
  $: heartbeatAt = parseUTC($trainingState?.heartbeat_at)
  let wallTime = ''
  let trainTime = ''
  let wallTimer = null

  function tick() {
    if (startedAt) {
      wallTime = formatElapsed(Date.now() - startedAt.getTime())
    }
    if (startedAt && heartbeatAt) {
      trainTime = formatElapsed(heartbeatAt.getTime() - startedAt.getTime())
    }
  }

  $: if (startedAt && !wallTimer) {
    tick()
    wallTimer = setInterval(tick, 1000)
  }
  // Update train clock when heartbeat changes
  $: if (heartbeatAt) tick()

  onDestroy(() => {
    if (wallTimer) clearInterval(wallTimer)
  })
</script>

<header class="status-bar">
  <div class="identity">
    <img src="/favicon.svg" alt="" class="app-icon" aria-hidden="true" />
    <h1>{displayName !== 'Player' ? displayName : 'Keisei'}</h1>
    <span class="phase-badge" class:stale={!alive}>{indicator.text}</span>
    <span class="epoch">Epoch {epoch.toLocaleString()}{#if totalEpochs} / {totalEpochs.toLocaleString()}{/if}</span>
    <span class="connection">{$connectionState}</span>
    <details class="run-details">
      <summary>Run details</summary>
      <dl>
        <dt>Architecture</dt><dd>{modelArch || 'Unavailable'}</dd>
        <dt>Phase</dt><dd>{phase || status}</dd>
        <dt>Step</dt><dd>{step.toLocaleString()}</dd>
        <dt>Games</dt><dd>{($trainingState?.episodes || 0).toLocaleString()}</dd>
        <dt>Wall clock</dt><dd>{wallTime || 'Unavailable'}</dd>
        <dt>Training clock</dt><dd>{trainTime || 'Unavailable'}</dd>
        <dt>CPU</dt><dd>{stats.cpu_percent != null ? `${stats.cpu_percent}%` : 'Unavailable'}</dd>
        {#each gpus as gpu,i}<dt>GPU {i}</dt><dd>{gpu.util_percent}% · {gpu.mem_used_mb} MB</dd>{/each}
      </dl>
      <p>{configTooltip}</p>
    </details>
  </div>
  <TabBar />
</header>
{#if $connectionState === 'connecting'}
  <div class="connecting-banner" role="status">
    Connecting to training server&hellip;
  </div>
{:else if $connectionState === 'reconnecting'}
  <div class="reconnect-banner" role="alert">
    Disconnected from server — reconnecting&hellip;
  </div>
{/if}

<style>
  .status-bar { display:flex; flex-wrap:wrap; justify-content:space-between; gap:4px 16px; align-items:center; padding:8px 12px; background:var(--bg-secondary); border-bottom:1px solid var(--border); }
  .identity { display:flex; gap:8px; align-items:center; flex-wrap:wrap; min-width:0; }
  .app-icon { width:24px; height:24px; }
  h1 { font:600 16px Georgia,serif; overflow-wrap:anywhere; max-width:32ch; }
  .phase-badge,.epoch,.connection { font-size:12px; color:var(--accent-teal); }
  .stale { color:var(--accent-gold); }
  .connection { color:var(--text-secondary); }
  summary { min-height:44px; padding:12px 8px; cursor:pointer; font-size:12px; }
  .run-details[open] { flex-basis:100%; }
  dl { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:6px 12px; font-size:13px; padding:8px; }
  dt { color:var(--text-secondary); }
  dd,p { overflow-wrap:anywhere; }
  p { font-size:12px; padding:8px; white-space:pre-line; }
  .connecting-banner,.reconnect-banner { padding:6px 12px; font-size:13px; text-align:center; color:var(--accent-teal); background:var(--bg-secondary); border-bottom:1px solid currentColor; }
  .reconnect-banner { color:var(--danger); }
  @media(max-width:600px) { .status-bar { padding:4px 8px; } .identity { gap:4px 8px; } h1 { max-width:22ch; font-size:14px; } }
</style>
