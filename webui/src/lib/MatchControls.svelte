<script>
  import { leagueEntries } from '../stores/league.js'
  import { showcaseGame, showcaseQueue, queueDepth, sidecarAlive, showcaseSpeed } from '../stores/showcase.js'
  import { sendShowcaseCommand, connectionState, showcaseCommandPending, showcaseCommandFeedback } from './ws.js'

  let selectedEntry1 = ''
  let selectedEntry2 = ''
  /**
   * Whether to render the full setup form. When a match is in progress we
   * collapse to a single "+ New match" button and the spectator UI gets the
   * screen real estate. The user can expand explicitly.
   */
  export let collapsed = false
  export let archived = false
  let expanded = false

  // Approximate ms-per-move so users understand what slow/normal/fast mean.
  // Keep in sync with backend SHOWCASE_SPEEDS in keisei/showcase/runner.py if
  // the table moves; this is purely informational.
  const SPEED_HINTS = {
    slow: '~2 s / move — easy to follow',
    normal: '~700 ms / move — balanced',
    fast: '~150 ms / move — quick games',
  }

  $: activeEntries = ($leagueEntries || []).filter(e => e.status === 'active')
  $: runningMatch = $showcaseQueue.find(q => q.status === 'running' && (!$showcaseGame || q.id === $showcaseGame.queue_id))

  // Keep local selection, connection and server confirmation state distinct.
  $: disabledReason = (() => {
    if ($connectionState !== 'connected') return 'Connect to the server before starting a match.'
    if ($showcaseCommandPending) return 'Waiting for the server to confirm the previous command.'
    if (!$sidecarAlive) return 'Showcase engine is offline — start the sidecar to enable matches.'
    if ($queueDepth >= 5) return `Queue is full (${$queueDepth} pending). Wait for one to start before adding more.`
    if (!selectedEntry1 || !selectedEntry2) return 'Pick a player for both Black and White.'
    if (selectedEntry1 === selectedEntry2) return 'Black and White must be different players.'
    if (!activeEntries.some(e => String(e.id) === selectedEntry1) || !activeEntries.some(e => String(e.id) === selectedEntry2)) return 'A selected player is no longer active. Pick both players again.'
    return null
  })()
  $: canStart = disabledReason === null

  function requestMatch() {
    if (!canStart) return
    const sent = sendShowcaseCommand({
      type: 'request_showcase_match',
      entry_id_1: selectedEntry1,
      entry_id_2: selectedEntry2,
      speed: $showcaseSpeed,
    })
    if (sent && collapsed) expanded = false
  }

  function changeSpeed(newSpeed) {
    if (archived || !runningMatch) return
    sendShowcaseCommand({ type: 'change_showcase_speed', queue_id: runningMatch.id, speed: newSpeed })
  }

  function toggleExpanded() {
    expanded = !expanded
  }
</script>

{#if collapsed && !expanded}
  <div class="collapsed-row">
    <button
      class="new-match-btn"
      on:click={toggleExpanded}
      aria-label="Open match setup form"
    >
      + New match
    </button>
    <div class="speed-controls compact" role="group" aria-label="Playback speed">
      {#each ['slow', 'normal', 'fast'] as s}
        <button
          class:active={runningMatch?.speed === s}
          aria-pressed={runningMatch?.speed === s}
          disabled={archived || !runningMatch || !$sidecarAlive || $connectionState !== 'connected' || !!$showcaseCommandPending}
          on:click={() => changeSpeed(s)}
          title={SPEED_HINTS[s]}
        >{s}</button>
      {/each}
    </div>
  </div>
{:else}
  <div class="match-controls" role="group" aria-label="Match setup">
    {#if collapsed}
      <button
        class="collapse-btn"
        on:click={toggleExpanded}
        aria-label="Hide match setup form"
        title="Hide setup"
      >×</button>
    {/if}
    <div class="entry-selectors">
      <select bind:value={selectedEntry1} aria-label="Black player">
        <option value="">Select black…</option>
        {#each activeEntries as entry}
          <option value={String(entry.id)}>
            {entry.display_name} ({entry.elo_rating?.toFixed(0) ?? '?'})
          </option>
        {/each}
      </select>
      <span class="vs">vs</span>
      <select bind:value={selectedEntry2} aria-label="White player">
        <option value="">Select white…</option>
        {#each activeEntries as entry}
          <option value={String(entry.id)}>
            {entry.display_name} ({entry.elo_rating?.toFixed(0) ?? '?'})
          </option>
        {/each}
      </select>
    </div>
    <div class="speed-controls" role="group" aria-label="New match speed">
      <span class="label">New match speed:</span>
      {#each ['slow', 'normal', 'fast'] as s}
        <button
          class:active={$showcaseSpeed === s}
          aria-pressed={$showcaseSpeed === s}
          on:click={() => showcaseSpeed.set(s)}
          title={SPEED_HINTS[s]}
        >{s}</button>
      {/each}
    </div>
    <button
      class="start-btn"
      on:click={requestMatch}
      disabled={!canStart}
      title={disabledReason || 'Start a new showcase match'}
      aria-describedby={disabledReason ? 'start-disabled-reason' : undefined}
    >Start Match</button>
    {#if disabledReason && $sidecarAlive}
      <!--
        Offline message is already announced by the role="alert" banner in
        ShowcaseView; restating it here would be the third copy. For other
        disabled reasons (queue full, same player picked, etc.) we still want
        an inline status message visible next to the button.
      -->
      <div id="start-disabled-reason" class="disabled-reason" role="status">{disabledReason}</div>
    {/if}
  </div>
{/if}

{#if $showcaseCommandFeedback}
  <p class="command-feedback" class:error={$showcaseCommandFeedback.kind === 'error'} role={$showcaseCommandFeedback.kind === 'error' ? 'alert' : 'status'}>
    {$showcaseCommandFeedback.message}
  </p>
{/if}

<style>
  .command-feedback { padding: 8px 12px; font-size: 13px; color: var(--text-secondary); }
  .command-feedback.error { color: var(--danger); }
  .collapsed-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
  }

  .new-match-btn {
    padding: 6px 14px;
    min-height: 44px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid var(--accent-teal);
    border-radius: 4px;
    background: transparent;
    color: var(--accent-teal);
    cursor: pointer;
  }
  .new-match-btn:hover { background: var(--badge-bg-teal); }
  .new-match-btn:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

  .match-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-bottom: 1px solid var(--border);
  }

  .collapse-btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    min-width: 44px;
    min-height: 44px;
    padding: 0;
  }
  .collapse-btn:hover { color: var(--text-primary); border-color: var(--text-secondary); }
  .collapse-btn:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

  .entry-selectors { display: flex; align-items: center; gap: 8px; min-width: 0; max-width: 100%; flex-wrap: wrap; }
  .vs { font-weight: 600; color: var(--text-muted); font-size: 13px; }

  select {
    max-width: 100%;
    padding: 6px 8px;
    min-height: 44px;
    font-size: 13px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-primary);
  }
  select:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

  .speed-controls { display: flex; align-items: center; gap: 4px; }
  .speed-controls .label { font-size: 12px; color: var(--text-secondary); }

  .speed-controls button {
    min-width:44px;
    padding: 4px 10px;
    min-height: 44px;
    font-size: 12px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    text-transform: capitalize;
  }
  .speed-controls.compact button { min-height: 44px; padding: 2px 8px; font-size: 11px; }

  .speed-controls button[aria-pressed='true'] {
    border-color: var(--tab-active-border);
    color: var(--tab-active-border);
    background: var(--tab-active-bg);
  }
  .speed-controls button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
  .speed-controls button:disabled { opacity: 0.5; cursor: not-allowed; }

  .start-btn {
    padding: 6px 16px;
    min-height: 44px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid var(--accent-teal);
    border-radius: 4px;
    background: var(--accent-teal);
    color: var(--action-text);
    cursor: pointer;
  }
  .start-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .start-btn:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

  .disabled-reason {
    font-size: 12px;
    color: var(--accent-gold);
    flex-basis: 100%;
  }
</style>
