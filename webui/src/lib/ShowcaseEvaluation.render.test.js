// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import { get } from 'svelte/store'
import CommentaryPanel from './CommentaryPanel.svelte'
import WinProbGraph from './WinProbGraph.svelte'
import { showcaseMoves, showcaseSelectedPly } from '../stores/showcase.js'

const charts = vi.hoisted(() => [])
// Vitest resolves Svelte's server lifecycle; schedule the chart mount after DOM creation.
vi.mock('svelte', async importOriginal => {
  const actual = await importOriginal()
  return { ...actual, onMount: callback => queueMicrotask(callback) }
})
vi.mock('uplot', () => ({ default: class {
  constructor(opts, data) { this.opts = opts; this.data = data; this.over = { getBoundingClientRect: () => ({ left: 0 }) }; charts.push(this) }
  setData(data) { this.data = data }
  setSize() {}
  redraw() {}
  destroy() {}
  posToVal(x) { return x }
} }))
const makeMove = (ply, player, score) => ({ ply, current_player: player === 'black' ? 'white' : 'black',
  evaluation_json: JSON.stringify({ version: 1, kind: 'outcome_score', player, score, position_ply: ply - 1,
    source: { architecture: 'resnet', contract: 'scalar' } }),
  usi_notation: 'P-7f', top_candidates: '[]', value_estimate: 0.99,
})
let component
const mount = (Component, props) => component = new Component({ target: document.body, props })
afterEach(() => { component?.$destroy(); document.body.innerHTML = ''; showcaseMoves.set([]); showcaseSelectedPly.set(null); charts.length = 0 })
it('commentary uses supplied archived evaluation and shows no neutral legacy fallback', async () => {
  showcaseMoves.set([makeMove(1, 'black', 0.8)])
  mount(CommentaryPanel, { displayedMove: makeMove(2, 'white', 0.8), scrubbing: true })
  expect(document.body.textContent).toContain('Black outcome estimate before move 2')
  expect(document.body.textContent).toContain('20.0%')
  expect(document.body.textContent).not.toContain('99.0%')
  component.$set({ displayedMove: { ply: 3, value_estimate: 0.5 } })
  await tick()
  expect(document.body.textContent).toContain('Estimate unavailable')
  expect(document.querySelector('.eval-bar-fill')).toBeNull()
})
it('graph plots pre-move Black values and gaps and exposes native selection buttons', async () => {
  const moves = [makeMove(1, 'black', 0.8), makeMove(2, 'white', 0.8), { ply: 3 }]
  showcaseSelectedPly.set(7)
  mount(WinProbGraph, { moves, selectedIndex: 1 })
  const selected = vi.fn()
  component.$on('select', selected)
  await tick()
  expect(charts.at(-1).data[0]).toEqual([0, 1, 2])
  expect(charts.at(-1).data[1][0]).toBeCloseTo(0.8)
  expect(charts.at(-1).data[1][1]).toBeCloseTo(0.2)
  expect(charts.at(-1).data[1][2]).toBeNull()
  const buttons = document.querySelectorAll('button')
  expect(buttons).toHaveLength(3)
  expect(buttons[1].getAttribute('aria-current')).toBe('true')
  buttons[1].click()
  expect(selected.mock.calls[0][0].detail).toEqual({ index: 1, move: moves[1] })
  expect(get(showcaseSelectedPly)).toBe(7)
  document.querySelector('.chart-host').dispatchEvent(new MouseEvent('click', { clientX: 1 }))
  expect(selected.mock.calls[1][0].detail.index).toBe(1)
})
