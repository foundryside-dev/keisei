<script>
  import { onMount } from 'svelte'
  import { connect, disconnect } from './lib/ws.js'
  import { games, selectedGame, selectedOpponent, laneAnnouncement } from './stores/games.js'
  import { activeTab, navigation } from './stores/navigation.js'
  import { trainingState } from './stores/training.js'
  import { learnerEntry, learnerRecentRecord } from './stores/league.js'
  import { latestMetrics } from './stores/metrics.js'
  import StatusIndicator from './lib/StatusIndicator.svelte'
  import GameThumbnail from './lib/GameThumbnail.svelte'
  import Board from './lib/Board.svelte'
  import BoardPosition from './lib/BoardPosition.svelte'
  import PieceTray from './lib/PieceTray.svelte'
  import MoveLog from './lib/MoveLog.svelte'
  import EvalBar from './lib/EvalBar.svelte'
  import MetricsGrid from './lib/MetricsGrid.svelte'
  import PlayerCard from './lib/PlayerCard.svelte'
  import LeagueView from './lib/LeagueView.svelte'
  import ShowcaseView from './lib/ShowcaseView.svelte'
  import AboutView from './lib/AboutView.svelte'
  import ShogiLegend from './lib/ShogiLegend.svelte'
  import { safeParse } from './lib/safeParse.js'
  import { audioEnabled, AUDIO_VOLUME } from './stores/audio.js'

  onMount(() => {
    connect()
    return disconnect
  })

  let audioEl
  let announceMoves = false
  let previousLanePly = null
  let moveAnnouncement = ''
  $: if (game && `${game.game_id}:${game.ply}` !== previousLanePly) {
    previousLanePly = `${game.game_id}:${game.ply}`
    moveAnnouncement = announceMoves ? `Lane ${game.game_id + 1}, ply ${game.ply}. ${game.current_player} to move.` : ''
  }
  // The audio element survives tab switches because it lives at App scope.
  // On reload with persisted "on", play() rejects with NotAllowedError until
  // the user provides a gesture this load. Keep the store unchanged in that
  // case so the button reflects the saved intent — only flip to off on real
  // failures (decode errors, missing source, etc).
  $: if (audioEl) {
    audioEl.volume = AUDIO_VOLUME
    if ($audioEnabled) {
      audioEl.play().catch((err) => {
        if (err?.name !== 'NotAllowedError') {
          audioEnabled.set(false)
        }
      })
    } else {
      audioEl.pause()
    }
  }

  $: game = $selectedGame
  $: board = game ? safeParse(game.board_json, game.board || []) : []
  $: hands = game ? safeParse(game.hands_json, game.hands || {}) : {}
  $: moveHistory = game?.move_history_json || '[]'

  // Learner info from training state
  $: learnerName = $trainingState?.display_name || $trainingState?.model_arch || 'Learner'
  $: learnerElo = $learnerEntry?.elo_rating ?? null
  $: learnerDetail = $trainingState
    ? `${$trainingState.model_arch || ''} · Epoch ${$trainingState.current_epoch || 0} · ${($trainingState.current_step || 0).toLocaleString()} steps`
    : ''

  // Seeded RNG for stable learner fun facts (keyed on display name)
  function seededPick(seed, pool) {
    let h = 0
    for (let i = 0; i < seed.length; i++) h = ((h << 5) - h + seed.charCodeAt(i)) | 0
    return pool[Math.abs(h) % pool.length]
  }

  const flavourPools = {
    'Favourite piece': ['Gold General', 'Silver General', 'Knight', 'Lance', 'Bishop', 'Rook', 'Promoted Pawn', 'Dragon Horse', 'Dragon King', 'King'],
    'Favourite philosopher': ['Musashi', 'Sun Tzu', 'Confucius', 'Turing', 'Shannon', 'Von Neumann', 'Bellman', 'Lao Tzu', 'Leibniz', 'Miyamoto'],
    'Favourite snack': ['Onigiri', 'Mochi', 'Dango', 'Taiyaki', 'Gradient soup', 'Loss crumble', 'Entropy tea', 'Batch noodles', 'Tensor rolls', 'Senbei'],
    'Training motto': ['"Loss goes down"', '"Explore everything"', '"Patience is policy"', '"Trust the gradient"', '"Variance is the enemy"', '"Clip wisely"', '"Entropy is freedom"', '"Value the position"', '"Every ply counts"', '"Promote early"'],
    'Lucky number': ['0.0001', '0.99', '42', '3.14', '2048', '0.95', '1e-8', '256', '0.2', '7.5M'],
  }

  $: learnerFlavour = (() => {
    const name = learnerName || 'Learner'
    const cats = Object.keys(flavourPools)
    const facts = []
    for (let i = 0; i < 3 && i < cats.length; i++) {
      const cat = cats[(Math.abs(name.length * 31 + i * 7) | 0) % cats.length]
      // avoid picking the same category twice
      if (!facts.find(f => f[0] === cat)) {
        facts.push([cat, seededPick(name + cat, flavourPools[cat])])
      }
    }
    return facts
  })()

  // Learner stats for PlayerCard
  $: learnerStats = (() => {
    const s = []
    if ($trainingState?.model_arch) s.push(['Architecture', $trainingState.model_arch])
    // Compact architecture summary from config
    try {
      const cfg = typeof $trainingState?.config_json === 'string'
        ? JSON.parse($trainingState.config_json) : $trainingState?.config_json
      if (cfg) {
        const mp = cfg.model?.params || cfg.model_params || {}
        const parts = []
        if (mp.num_blocks && mp.channels) parts.push(`b${mp.num_blocks}c${mp.channels}`)
        if (mp.se_reduction) parts.push(`SE-${mp.se_reduction}`)
        if (mp.global_pool_channels) parts.push(`gp${mp.global_pool_channels}`)
        if (parts.length) s.push(['Topology', parts.join(' · ')])
      }
    } catch { /* config not available yet */ }
    const m = $latestMetrics
    if (m) {
      if (m.policy_loss != null) s.push(['Policy loss', m.policy_loss.toFixed(4)])
      if (m.value_loss != null) s.push(['Value loss', m.value_loss.toFixed(4)])
      if (m.entropy != null) s.push(['Entropy', m.entropy.toFixed(4)])
      if (m.value_accuracy != null) s.push(['Value accuracy', (m.value_accuracy * 100).toFixed(1) + '%'])
    }
    // Recent result feed, from the learner's participant perspective.
    if ($learnerRecentRecord) {
      const { w, l, d, rounds } = $learnerRecentRecord
      s.push([`Recent W/L/D (${rounds} round${rounds === 1 ? '' : 's'})`, `${w} / ${l} / ${d}`])
    }
    return s
  })()

  $: learnerFacts = learnerFlavour.map(([label, value]) => [label, value])

  // Opponent info from selected game
  $: opp = $selectedOpponent
  $: opponentName = opp ? opp.display_name : (game ? 'Self-play' : 'No opponent yet')
  $: opponentElo = opp?.elo_rating ?? null
  $: opponentDetail = opp
    ? `${opp.architecture} · Epoch ${opp.created_epoch}`
    : (game
        ? 'Learner playing both sides — no league snapshot for this game.'
        : 'Waiting for a game to start.')

  // Opponent stats for PlayerCard
  $: opponentStats = (() => {
    if (!opp) return []
    const s = []
    s.push(['Architecture', opp.architecture])
    const mp = opp.model_params || {}
    const parts = []
    if (mp.num_blocks && mp.channels) parts.push(`b${mp.num_blocks}c${mp.channels}`)
    if (mp.se_reduction) parts.push(`SE-${mp.se_reduction}`)
    if (mp.global_pool_channels) parts.push(`gp${mp.global_pool_channels}`)
    if (parts.length) s.push(['Topology', parts.join(' · ')])
    s.push(['Snapshot epoch', String(opp.created_epoch)])
    s.push(['Games played', String(opp.games_played)])
    if (opp.created_at) {
      const d = new Date(opp.created_at)
      s.push(['Born', d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })])
    }
    return s
  })()

  $: opponentFacts = opp?.flavour_facts ? opp.flavour_facts.map(([label, value]) => [label, value]) : []
</script>

<div class="app">
  <a href={`#${$activeTab}-main`} class="skip-nav">Skip to content</a>
  <audio bind:this={audioEl} src="/audio/lofi.opus" loop preload="none"></audio>
  <StatusIndicator />
  {#if $navigation.error}<p class="navigation-error" role="alert">{$navigation.error}</p>{/if}

  {#if $activeTab === 'training'}
    <div id="training-main" class="main-content" role="tabpanel" tabindex="-1" aria-labelledby="tab-training">
      <div class="sr-only" role="status">{#key $laneAnnouncement.revision}<span>{$laneAnnouncement.message}</span>{/key}</div>
      <div class="sr-only" role="status">{moveAnnouncement}</div>
      <div class="player-panel">
        <PlayerCard role="learner" name={learnerName} elo={learnerElo} detail={learnerDetail} stats={learnerStats} facts={learnerFacts} />
        <div class="vs-separator">VS</div>
        <PlayerCard role="opponent" name={opponentName} elo={opponentElo} detail={opponentDetail} stats={opponentStats} facts={opponentFacts} tierRole={opp?.role} />
      </div>

      <section id="game-panel" class="game-panel" aria-label="Game viewer">
        {#if game}
          <div class="game-view">
            <div class="board-area">
              <PieceTray color="white" hand={hands.white || {}} />
              <Board
                board={board}
                inCheck={!!game.in_check}
                currentPlayer={game.current_player || 'black'}
              />
              <PieceTray color="black" hand={hands.black || {}} />
              <BoardPosition {board} {hands} currentPlayer={game.current_player || 'black'} />
              <label class="announce-toggle"><input type="checkbox" bind:checked={announceMoves} /> Announce following moves</label>
            </div>

            <div class="eval-area">
              <EvalBar
                value={game.value_estimate || 0}
                currentPlayer={game.current_player || 'black'}
              />
            </div>

            <div class="info-area">
              <div class="game-info">
                <div class="info-row">
                  <span class="label">Game {(game.game_id || 0) + 1}</span>
                  <span class="value">{game.current_player || 'black'} to move</span>
                </div>
                <div class="info-row">
                  <span class="label">Ply</span>
                  <span class="value">{game.ply || 0}</span>
                </div>
                <div class="info-row">
                  <span class="label">Result</span>
                  <span class="value result"
                    class:in-progress={game.result === 'in_progress'}
                    class:terminal={game.result !== 'in_progress'}
                  >
                    {#if game.result === 'in_progress'}In progress{:else}&#10003; {(game.result || '').replaceAll('_', ' ')}{/if}
                  </span>
                </div>
              </div>

              <MoveLog moveHistoryJson={moveHistory} />
            </div>

            <div class="legend-area">
              <ShogiLegend />
            </div>
          </div>
        {:else}
          <div class="no-game">
            <p>Waiting for game data&hellip;</p>
            <p class="no-game-hint">Connect a training session to see live games.</p>
          </div>
        {/if}
      </section>
      <aside class="thumbnail-panel" aria-label="Game list">
        <div class="desktop-games"><h2>Games ({$games.length})</h2><div class="thumb-grid">{#each $games as g (g.game_id)}<GameThumbnail game={g} />{/each}</div></div>
        <details class="game-selector compact-games">
          <summary>Choose game ({$games.length}) · {game ? `Lane ${game.game_id + 1}` : 'No lane'}</summary>
          <div class="thumb-grid">
            {#each $games as g (g.game_id)}<GameThumbnail game={g} />{/each}
          </div>
        </details>
      </aside>
      <details class="metrics-panel">
        <summary>Training metrics</summary>
        <MetricsGrid />
      </details>
    </div>
  {:else if $activeTab === 'league'}
    <LeagueView />
  {:else if $activeTab === 'showcase'}
    <ShowcaseView />
  {:else if $activeTab === 'about'}
    <AboutView />
  {/if}
</div>

<style>
  .skip-nav { position:absolute; left:-9999px; top:0; z-index:100; padding:12px; background:var(--accent-ink); color:var(--action-text); }
  .skip-nav:focus { left:0; }
  .app { min-height:100dvh; background:var(--bg-primary); }
  .main-content { display:grid; grid-template-columns:200px minmax(0,1fr); gap:12px; padding:12px; align-items:start; min-width:0; }
  .main-content > * { min-width:0; }
  .player-panel { grid-column:2; display:flex; gap:8px; align-items:start; }
  .vs-separator { padding:14px 0; color:var(--text-muted); font-size:12px; }
  .game-panel { grid-column:2; }
  .game-view { display:grid; grid-template-columns:minmax(0,1fr) 26px minmax(200px,0.6fr); gap:12px; align-items:start; }
  .board-area { min-width:0; width: min(100%, calc(100dvh - 300px), 636px); --board-size:100%; }
  .info-area { min-width:0; display:flex; flex-direction:column; gap:8px; max-height:650px; }
  .game-info { padding:10px; border:1px solid var(--border); border-radius:6px; font-size:13px; }
  .info-row { display:flex; justify-content:space-between; gap:8px; padding:4px 0; }
  .label { color:var(--text-secondary); }
  .result.terminal { color:var(--accent-teal); }
  .legend-area { grid-column:1/-1; }
  .thumbnail-panel { grid-column:1; grid-row:1/3; }
  .game-selector { border:1px solid var(--border); border-radius:6px; padding:0 8px; }
  summary { cursor:pointer; min-height:44px; padding:12px 0; font-size:13px; font-weight:600; }
  .thumb-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:8px 0; max-height:65dvh; overflow:auto; }
  .metrics-panel { grid-column:1/-1; border-top:1px solid var(--border); padding:0 8px; }
  .announce-toggle { display:flex; gap:8px; align-items:center; min-height:44px; font-size:13px; }
  .no-game { padding:36px 12px; color:var(--text-secondary); }
  .no-game-hint { margin-top:8px; font-size:13px; }
  .compact-games { display:none; }
  .desktop-games h2 { font-size:13px; padding:8px; color:var(--text-secondary); }
  .navigation-error { padding:12px; color:var(--danger); font-size:13px; }
  @media(max-width:1023px), (max-height:650px) {
    .main-content { display:flex; flex-direction:column; padding:8px; gap:8px; }
    .player-panel,.game-panel,.thumbnail-panel,.metrics-panel { width:100%; }
    .game-panel,.game-view { display:contents; }
    .player-panel { order:1; }
    .board-area { order:2; }
    .thumbnail-panel { order:3; }
    .info-area { order:4; }
    .legend-area { order:5; }
    .metrics-panel { order:6; }
    .desktop-games { display:none; }
    .compact-games { display:block; }
    .board-area { width:min(100%,636px); align-self:center; }
    .eval-area { display:none; }
    .info-area { width:100%; max-height:none; }
    .info-area :global(.move-log) { max-height:300px; }
    .thumb-grid { grid-template-columns:repeat(auto-fill,minmax(80px,1fr)); }
    .legend-area { width:100%; }
  }
</style>
