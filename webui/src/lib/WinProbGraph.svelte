<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import { showcaseSelectedPly, showcaseDisplayedMove, showcaseMoves } from '../stores/showcase.js'
  import { evaluationHistory, validateEvaluation } from './showcaseEvaluation.js'
  import { theme } from '../stores/theme.js'
  import { resolveThemeColors } from './chartHelpers.js'
  import uPlot from 'uplot'

  export let moves = undefined
  export let displayedMove = undefined
  export let selectedIndex = undefined
  const dispatch = createEventDispatcher()
  $: effectiveMoves = moves === undefined ? $showcaseMoves : moves
  $: history = evaluationHistory(effectiveMoves)
  $: currentMove = displayedMove !== undefined ? displayedMove
    : selectedIndex != null ? effectiveMoves[selectedIndex] : moves === undefined ? $showcaseDisplayedMove : effectiveMoves.at(-1)
  $: currentEvaluation = validateEvaluation(currentMove)

  let chartEl, containerEl, chart = null, resizeObserver = null
  let markerPly = null, markerColor = '#c8962e'
  const buildData = history => [history.map(h => h.positionPly), history.map(h => h.value)]
  function selectMove(index) {
    dispatch('select', { index, move: effectiveMoves[index] })
    if (moves === undefined) showcaseSelectedPly.set(index)
  }
  function drawMarker(u) {
    if (markerPly == null) return
    const x = u.valToPos(markerPly, 'x', true)
    if (!Number.isFinite(x)) return
    const ctx = u.ctx
    ctx.save()
    ctx.strokeStyle = markerColor
    ctx.lineWidth = 2
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    ctx.moveTo(x, u.bbox.top)
    ctx.lineTo(x, u.bbox.top + u.bbox.height)
    ctx.stroke()
    ctx.restore()
  }
  function palette() {
    const c = resolveThemeColors()
    const root = getComputedStyle(document.documentElement)
    return { axis: c.textColor || '#888', grid: c.gridColor || '#333',
      teal: root.getPropertyValue('--accent-teal').trim() || '#4db8a8',
      gold: root.getPropertyValue('--accent-gold').trim() || '#c8962e' }
  }
  const currentWidth = () => Math.max(120, containerEl?.clientWidth || 300)
  function rebuildChart() {
    if (!chartEl) return
    chart?.destroy()
    const p = palette()
    markerColor = p.gold
    chart = new uPlot({
      width: currentWidth(), height: 120,
      cursor: { show: false }, legend: { show: false },
      scales: { x: { time: false }, y: { range: [0, 1] } },
      axes: [
        { size: 28, font: '12px sans-serif', stroke: p.axis, grid: { stroke: p.grid },
          values: (u, vals) => vals.map(v => Number.isInteger(v) ? v : '') },
        { size: 48, font: '12px sans-serif', stroke: p.axis, grid: { stroke: p.grid },
          values: (u, vals) => vals.map(v => (v * 100).toFixed(0) + '%') },
      ],
      series: [{}, { stroke: p.teal, width: 2, fill: p.teal + '1f', spanGaps: false }],
      hooks: { draw: [drawMarker] },
    }, buildData(history), chartEl)
  }
  function onChartClick(event) {
    if (!chart || !history.length) return
    const positionPly = chart.posToVal(event.clientX - chart.over.getBoundingClientRect().left, 'x')
    if (!Number.isFinite(positionPly)) return
    const closest = history.reduce((a, b) => Math.abs(a.positionPly - positionPly) <= Math.abs(b.positionPly - positionPly) ? a : b)
    selectMove(closest.index)
  }
  onMount(() => {
    rebuildChart()
    containerEl?.addEventListener('click', onChartClick)
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => chart?.setSize({ width: currentWidth(), height: 120 }))
      resizeObserver.observe(containerEl)
    }
  })
  const unsubTheme = theme.subscribe(() => { if (chartEl) requestAnimationFrame(rebuildChart) })
  onDestroy(() => {
    unsubTheme()
    containerEl?.removeEventListener('click', onChartClick)
    resizeObserver?.disconnect()
    chart?.destroy()
  })
  $: if (chart && history) chart.setData(buildData(history))
  $: if (chart) {
    markerPly = currentEvaluation.available ? currentEvaluation.positionPly : null
    chart.redraw(false, true)
  }
</script>

<div class="win-prob-graph">
  <h3 class="section-label">Black outcome estimate</h3>
  <div class="chart-host" bind:this={containerEl} aria-hidden="true"><div bind:this={chartEl}></div></div>
  <p class="axis-hint">Pre-move positions; higher favors Black. Draws receive half credit. Estimates alternate between the players’ models and are not calibrated win probabilities. Missing estimates appear as gaps.</p>
  <details class="position-values">
    <summary>Position estimates ({history.length})</summary>
    {#if history.length}
      <ol>
        {#each history as point}
          <li><button type="button" on:click={() => selectMove(point.index)} aria-current={currentMove?.ply === point.move.ply ? 'true' : undefined}>
            {#if point.evaluation.available}
              {point.evaluation.label}: {(point.value * 100).toFixed(1)}%
            {:else}
              Before move {point.move.ply}: Estimate unavailable — {point.evaluation.reason}
            {/if}
          </button></li>
        {/each}
      </ol>
    {:else}<p>No stored moves yet.</p>{/if}
  </details>
</div>

<style>
  .win-prob-graph { padding: 8px; min-width: 0; }
  .section-label { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; margin: 0 0 4px; }
  .chart-host { width: 100%; min-width: 0; cursor: pointer; }
  .axis-hint { margin: 4px 0 0; font-size: 12px; color: var(--text-secondary); line-height: 1.4; }
  .position-values { margin-top: 8px; font-size: 12px; color: var(--text-secondary); }
  summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; }
  ol { padding-left: 22px; max-height: 260px; overflow: auto; }
  button { min-height: 44px; width: 100%; text-align: left; color: var(--text-primary); background: var(--bg-secondary); border: 1px solid var(--border-subtle); border-radius: 4px; padding: 6px; cursor: pointer; }
  li + li { margin-top: 4px; }
  button[aria-current] { border-color: var(--accent-teal); }
</style>
