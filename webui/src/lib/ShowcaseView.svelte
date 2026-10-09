<script>
  import { onDestroy, tick } from 'svelte'
  import { showcaseGame, showcaseMoves, sidecarAlive, showcaseHeatmapEnabled } from '../stores/showcase.js'
  import { navigation, setReplayPly, watchLatestMatch } from '../stores/navigation.js'
  import { createViewedMatch } from '../stores/viewedMatch.js'
  import { safeParse } from './safeParse.js'
  import { parseUsi } from './usiCoords.js'
  import { replayAction } from './replayKeyboard.js'
  import { validateEvaluation } from './showcaseEvaluation.js'
  import Board from './Board.svelte'
  import BoardPosition from './BoardPosition.svelte'
  import PieceTray from './PieceTray.svelte'
  import MoveLog from './MoveLog.svelte'
  import MatchControls from './MatchControls.svelte'
  import CommentaryPanel from './CommentaryPanel.svelte'
  import WinProbGraph from './WinProbGraph.svelte'
  import MatchQueue from './MatchQueue.svelte'
  import MatchScorecard from './MatchScorecard.svelte'
  import ShowcaseStatsBanner from './ShowcaseStatsBanner.svelte'

  const viewed = createViewedMatch({ navigationStore: navigation, liveGameStore: showcaseGame, liveMovesStore: showcaseMoves })
  onDestroy(viewed.destroy)
  let announceMoves = false
  let announcement = ''
  let previousMove = ''
  let copyFeedback = ''
  let contentElement
  let boardElement
  let boardSize = null
  function fitBoard(node) {
    boardElement = node
    contentElement = node.parentElement
    function sizeBoard() {
      if (!contentElement || !boardElement) return
      const compact = window.matchMedia('(max-width:1023px), (max-height:650px)').matches
      if (compact) { boardSize = null; return }
      const column = Number.parseFloat(getComputedStyle(contentElement).gridTemplateColumns)
      const top = boardElement.getBoundingClientRect().top + window.scrollY
      const available = Math.floor(Math.min(column || 636, 636, Math.max(200, window.innerHeight - top - 180)))
      if (boardSize !== available) boardSize = available
    }
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(sizeBoard) : null
    if (observer) {
      observer.observe(contentElement)
      observer.observe(contentElement.parentElement)
      for (const element of document.querySelectorAll('.status-bar,.scorecard,.viewer-toolbar')) observer.observe(element)
    }
    window.addEventListener('resize',sizeBoard)
    tick().then(sizeBoard)
    return { destroy() { observer?.disconnect(); window.removeEventListener('resize',sizeBoard) } }
  }
  $: game = $viewed.game
  $: moves = $viewed.moves
  $: move = $viewed.displayedMove
  $: board = move ? safeParse(move.board_json, []) : []
  $: hands = move ? safeParse(move.hands_json, {}) : {}
  $: selectedMoveIdx = $viewed.following ? moves.length - 1 : $viewed.selectedIndex
  $: finished = game && game.status !== 'in_progress'
  $: viewerState = $viewed.archived ? `Replay · ply ${move?.ply ?? 0}` : !$viewed.following ? `Paused at ply ${move?.ply ?? 0}` : finished ? 'Finished' : 'Live'
  $: tailLabel = finished || $viewed.archived ? 'Latest move' : 'Live'
  $: evaluation = validateEvaluation(move)
  $: moveHistoryJson = JSON.stringify(moves.map(m => ({ action: m.action_index, notation: m.usi_notation || m.move_usi })))
  $: coords = parseUsi(move?.move_usi || move?.usi_notation || '')
  $: heatmap = (() => {
    if (!$showcaseHeatmapEnabled) return null
    const raw = safeParse(move?.move_heatmap_json, null)
    if (!raw || typeof raw !== 'object') return null
    const out = {}
    for (const [usi,prob] of Object.entries(raw)) {
      const parsed = parseUsi(usi)
      if (parsed && Number.isFinite(prob) && prob >= 0 && prob <= 1) out[parsed.toIdx] = (out[parsed.toIdx] || 0) + prob
    }
    return out
  })()
  $: if (move && `${game?.id}:${move.ply}` !== previousMove) {
    previousMove = `${game?.id}:${move.ply}`
    announcement = announceMoves && $viewed.following && !$viewed.archived ? `Ply ${move.ply}: ${move.current_player === 'black' ? 'White' : 'Black'} plays ${move.usi_notation || move.move_usi}. ${move.current_player} to move.` : ''
  }
  function selectIndex(index) {
    if (!game) return
    if (index < 0) { setReplayPly(null, $viewed.explicitMatch ? game.id : null); return }
    const target = moves[Math.max(0, Math.min(index, moves.length - 1))]
    if (target) setReplayPly(target.ply, game.id)
  }
  function step(delta) { if (moves.length) selectIndex(Math.max(0, Math.min(moves.length - 1, selectedMoveIdx + delta))) }
  function toggleFollowing() { if ($viewed.following) selectIndex(moves.length - 1); else selectIndex(-1) }
  function keydown(event) {
    const action = replayAction(event)
    if (!action) return
    event.preventDefault()
    if (action.step) step(action.step)
    else if (action === 'first') selectIndex(0)
    else if (action === 'follow') selectIndex(-1)
    else if (action === 'pause') toggleFollowing()
    else if (action === 'heatmap') showcaseHeatmapEnabled.update(value => !value)
  }
  async function copyLink() {
    const url = new URL(window.location.href)
    url.searchParams.set('view','showcase')
    url.searchParams.delete('entry')
    if (game) url.searchParams.set('match',String(game.id))
    if (move) url.searchParams.set('ply',String(move.ply))
    try { await navigator.clipboard.writeText(url.href); copyFeedback = 'Link copied.' }
    catch { copyFeedback = `Could not copy the link. Select and copy: ${url.href}` }
  }
</script>

<div id="showcase-main" class="showcase-view" role="tabpanel" tabindex="-1" aria-labelledby="tab-showcase">
  <div class="sr-only" role="status">{announcement}</div>
  <ShowcaseStatsBanner />
  {#if !$sidecarAlive}<p class="offline-banner" role="alert"><strong>Match engine is offline.</strong> Saved matches remain available. Start the sidecar to enable live matches.</p>{/if}
  <MatchControls collapsed={game != null} archived={$viewed.archived} />
  {#if $viewed.loading}<p class="notice" role="status">Loading saved match…</p>
  {:else if $viewed.error}<div class="notice" role="alert"><p>{$viewed.error}</p><button on:click={viewed.retry}>Retry saved match</button><button on:click={watchLatestMatch}>Watch latest match</button></div>
  {:else if game}
    <MatchScorecard {game} displayedMove={move} scrubbing={!$viewed.following} />
    <div class="viewer-toolbar">
      <strong role="status">{viewerState}</strong>
      {#if $viewed.explicitMatch}<button on:click={watchLatestMatch}>Watch latest match</button>{/if}
      <button on:click={copyLink}>Copy link to this position</button>
      <span role="status">{copyFeedback}</span>
    </div>
    {#if $viewed.status}<p class="notice" role="status">{$viewed.status}</p>{/if}
    <main bind:this={contentElement} class="game-content" aria-label="Match viewer">
      <!-- svelte-ignore a11y-no-noninteractive-tabindex a11y-no-noninteractive-element-interactions -->
      <section use:fitBoard bind:this={boardElement} style:width={boardSize == null ? null : `${boardSize}px`} class="board-side" aria-label="Replay keyboard controls" tabindex="0" on:keydown={keydown} aria-describedby="replay-shortcuts">
        <PieceTray color="white" hand={hands.white || {}} />
        <Board {board} inCheck={!!move?.in_check} currentPlayer={move?.current_player || 'black'} lastMoveFromIdx={coords?.fromIdx ?? -1} lastMoveToIdx={coords?.toIdx ?? -1} {heatmap} />
        <PieceTray color="black" hand={hands.black || {}} />
        {#if moves.length}
          <div class="scrubber-row" role="group" aria-label="Replay scrubber">
            <button on:click={() => selectIndex(0)} aria-label="Jump to first stored ply">⏮</button>
            <button on:click={() => step(-1)} aria-label="Previous ply">◀</button>
            <input type="range" min="0" max={Math.max(0,moves.length - 1)} value={selectedMoveIdx} on:input={event => selectIndex(Number(event.target.value))} aria-label="Scrub to ply" aria-valuetext={`Stored ply ${move?.ply ?? 0}`} />
            <button on:click={() => step(1)} aria-label="Next ply">▶</button>
            <button on:click={() => selectIndex(-1)} aria-pressed={$viewed.following}>{tailLabel}</button>
          </div>
          <button on:click={toggleFollowing}>{$viewed.following ? 'Pause following' : 'Resume following'}</button>
        {/if}
        <div class="analysis-cluster">
          <button on:click={() => showcaseHeatmapEnabled.update(value => !value)} aria-pressed={$showcaseHeatmapEnabled}>Heatmap: {$showcaseHeatmapEnabled ? 'On' : 'Off'}</button>
          {#if $showcaseHeatmapEnabled}<span>Gold overlay: stronger = more policy weight</span>{/if}
          <label><input type="checkbox" bind:checked={announceMoves} /> Announce following moves</label>
        </div>
        <p id="replay-shortcuts" class="kbd-hints">Focus this viewer: ←/→ step, Shift+arrows 5, Home first, End latest/resume, Space pause/resume following, H heatmap.</p>
        <BoardPosition {board} {hands} currentPlayer={move?.current_player || 'black'} />
      </section>
      <aside class="analysis-side" aria-label="Match analysis">
        {#if evaluation.available}<div class="outcome" role="img" aria-label={`${evaluation.label}: ${(evaluation.blackScore*100).toFixed(1)}%`}><div style={`width:${evaluation.blackScore*100}%`}></div></div>{/if}
        <CommentaryPanel displayedMove={move} scrubbing={!$viewed.following} />
        <WinProbGraph {moves} displayedMove={move} selectedIndex={selectedMoveIdx} on:select={event => selectIndex(event.detail.index)} />
        <MoveLog {moveHistoryJson} interactive={true} selectedIdx={selectedMoveIdx} following={$viewed.following} {tailLabel} on:select={event => selectIndex(event.detail.idx)} />
      </aside>
    </main>
  {:else}<main class="no-game"><h2>No match available</h2><p>Choose two league players in New match to watch them play. Connect to the server and start the sidecar if the engine is offline.</p></main>{/if}
  <MatchQueue />
</div>

<style>
  .showcase-view { min-width:0; }
  .offline-banner,.notice { padding:8px 12px; color:var(--danger); font-size:13px; background:var(--badge-bg-danger); overflow-wrap:anywhere; }
  .viewer-toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:4px 12px; font-size:13px; }
  .game-content { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr); gap:16px; padding:8px 12px; align-items:start; }
  .board-side { min-width:0; width:min(100%,calc(100dvh - 500px),636px); --board-size:100%; justify-self:center; }
  .scrubber-row { display:flex; gap:4px; align-items:center; margin-top:4px; }
  button { min-height:44px; min-width:44px; padding:8px; border:1px solid var(--text-muted); background:var(--bg-secondary); color:var(--text-primary); border-radius:4px; cursor:pointer; font-size:12px; }
  button[aria-pressed='true'] { border-color:var(--accent-teal); color:var(--accent-teal); background:var(--bg-selected); }
  input[type='range'] { flex:1; min-width:0; height:44px; accent-color:var(--accent-teal); }
  .analysis-cluster { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:4px; font-size:12px; }
  label { display:flex; gap:8px; align-items:center; min-height:44px; }
  .kbd-hints { color:var(--text-secondary); font-size:12px; line-height:1.5; margin-top:4px; }
  .analysis-side { min-width:0; display:flex; flex-direction:column; gap:8px; }
  .analysis-side :global(.move-log) { max-height:300px; }
  .outcome { height:8px; background:var(--eval-white); border:1px solid var(--text-muted); border-radius:3px; overflow:hidden; }
  .outcome > div { height:100%; background:var(--eval-black); }
  .no-game { padding:24px; color:var(--text-secondary); }
  .no-game h2 { font-size:18px; margin-bottom:8px; }
  @media(max-width:1023px), (max-height:650px) {
    .game-content { display:flex; flex-direction:column; padding:8px; gap:12px; }
    .board-side { width:min(100%,636px); align-self:center; }
    .analysis-side { width:100%; }
  }
</style>
