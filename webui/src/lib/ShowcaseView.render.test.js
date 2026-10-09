// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import { get } from 'svelte/store'
import ShowcaseView from './ShowcaseView.svelte'
import { navigation } from '../stores/navigation.js'
import { showcaseGame, showcaseMoves, showcaseQueue, sidecarAlive, showcaseHeatmapEnabled } from '../stores/showcase.js'

vi.hoisted(() => { globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) })
vi.mock('./ws.js', async () => {
  const { writable } = await import('svelte/store')
  return { sendShowcaseCommand: vi.fn(), connectionState: writable('connected'), showcaseCommandPending: writable(null), showcaseCommandFeedback: writable(null) }
})
vi.mock('uplot', () => ({ default: class {
  setData() {} redraw() {} destroy() {} setSize() {}
} }))

// Use browser lifecycle hooks; Vitest's Node export conditions otherwise
// resolve the public Svelte module to its SSR no-op lifecycle functions.
vi.mock('svelte', async () => import('svelte/internal'))

let component
const match = (id = 9) => ({ id, queue_id: id === 9 ? 42 : 41, status: id === 9 ? 'in_progress' : 'black_wins', name_black: 'Black player', name_white: 'White player', total_ply: 3 })
const move = ply => ({ game_id: 9, ply, current_player: ply % 2 ? 'white' : 'black', board_json: '[]', hands_json: '{}', usi_notation: ['7g7f', '3c3d', '2g2f', '8c8d'][ply - 1], move_usi: ['7g7f', '3c3d', '2g2f', '8c8d'][ply - 1] })
const settle = async () => { await Promise.resolve(); await tick(); await tick(); await Promise.resolve(); await tick() }
const button = text => [...document.querySelectorAll('button')].find(node => node.textContent.trim() === text)
const stateLabel = () => document.querySelector('.viewer-toolbar strong')?.textContent
const key = (target, value, options = {}) => {
  const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...options })
  target.dispatchEvent(event)
  return event
}

beforeEach(async () => {
  history.replaceState(null, '', '/?view=showcase')
  window.dispatchEvent(new PopStateEvent('popstate'))
  showcaseGame.set(match()); showcaseMoves.set([move(1), move(2), move(3)])
  showcaseQueue.set([{ id: 42, status: 'running', speed: 'normal' }]); sidecarAlive.set(true); showcaseHeatmapEnabled.set(false)
  vi.stubGlobal('fetch', vi.fn(async url => {
    const id = Number(String(url).split('/').at(-1))
    return { ok: true, json: async () => ({ game: match(id), moves: [move(1), move(2), move(3)].map(row => ({ ...row, game_id: id })) }) }
  }))
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } })
  component = new ShowcaseView({ target: document.body })
  await settle()
})
afterEach(() => { component.$destroy(); document.body.innerHTML = ''; vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('labels a paused tail immediately and keeps it pinned when another move arrives', async () => {
  expect(stateLabel()).toBe('Live')
  button('Pause following').click(); await settle()
  expect(stateLabel()).toBe('Paused at ply 3')
  expect(get(navigation)).toMatchObject({ matchId: 9, ply: 3 })
  showcaseMoves.set([move(1), move(2), move(3), move(4)]); await settle()
  expect(stateLabel()).toBe('Paused at ply 3')
  expect(document.querySelector('input[type="range"]').value).toBe('2')
  button('Resume following').click(); await settle()
  expect(stateLabel()).toBe('Live')
  expect(document.querySelector('input[type="range"]').value).toBe('3')
})

it('clamps Previous and Shift+Left at the first stored position without resuming', async () => {
  document.querySelector('[aria-label="Jump to first stored ply"]').click(); await settle()
  expect(stateLabel()).toBe('Paused at ply 1')
  document.querySelector('[aria-label="Previous ply"]').click(); await settle()
  expect(stateLabel()).toBe('Paused at ply 1')
  key(document.querySelector('[aria-label="Replay keyboard controls"]'), 'ArrowLeft', { shiftKey: true }); await settle()
  expect(stateLabel()).toBe('Paused at ply 1')
  expect(get(navigation).ply).toBe(1)
})

it('keeps following when Next or a forward shortcut is used at the live tail', async () => {
  document.querySelector('[aria-label="Next ply"]').click(); await settle()
  const region = document.querySelector('[aria-label="Replay keyboard controls"]')
  key(region, 'ArrowRight'); key(region, 'ArrowRight', { shiftKey: true }); await settle()
  expect(stateLabel()).toBe('Live')
  expect(get(navigation)).toMatchObject({ matchId: null, ply: null })
  showcaseMoves.set([move(1), move(2), move(3), move(4)]); await settle()
  expect(document.querySelector('input[type="range"]').value).toBe('3')
  button('Pause following').click(); await settle()
  document.querySelector('[aria-label="Next ply"]').click(); await settle()
  expect(stateLabel()).toBe('Paused at ply 4')
})

it.each(['draw', 'black_win', 'white_win', 'abandoned'])('does not claim a next turn for a %s match', async status => {
  showcaseGame.set({ ...match(), status }); await settle()
  const footer = document.querySelector('.footer-strip')
  expect(footer.textContent).toContain(status.replaceAll('_', ' '))
  expect(footer.textContent).toContain('Ply 3')
  expect(footer.textContent).not.toContain('to move')
})

it('offers useful recovery without a no-op retry for a malformed route', async () => {
  history.replaceState(null, '', '/?view=showcase&match=9&ply=bad')
  window.dispatchEvent(new PopStateEvent('popstate')); await settle()
  expect(document.querySelector('.notice[role="alert"]')).not.toBeNull()
  expect(button('Retry saved match')).toBeUndefined()
  expect(fetch).not.toHaveBeenCalled()
  button('Watch latest match').click(); await settle()
  expect(stateLabel()).toBe('Live')
})

it('keeps Retry available for saved-match request failures', async () => {
  fetch.mockRejectedValueOnce(new Error('Connection failed'))
  history.replaceState(null, '', '/?view=showcase&match=8')
  window.dispatchEvent(new PopStateEvent('popstate')); await settle()
  expect(button('Retry saved match')).toBeDefined()
  button('Retry saved match').click(); await settle()
  expect(stateLabel()).toBe('Replay · ply 3')
})

it('scopes keyboard shortcuts to the region and preserves native buttons, summaries and move-history navigation', async () => {
  const region = document.querySelector('[aria-label="Replay keyboard controls"]')
  const summary = region.querySelector('summary')
  const heatmap = button('Heatmap: Off')
  expect(key(summary, ' ').defaultPrevented).toBe(false)
  expect(key(heatmap, ' ').defaultPrevented).toBe(false)
  expect(key(document.querySelector('[data-move-log]'), 'Home').defaultPrevented).toBe(false)
  expect(key(window, ' ').defaultPrevented).toBe(false)
  await settle()
  expect(stateLabel()).toBe('Live')
  expect(get(showcaseHeatmapEnabled)).toBe(false)
  heatmap.click(); await settle()
  expect(get(showcaseHeatmapEnabled)).toBe(true)
  expect(key(region, ' ').defaultPrevented).toBe(true)
  await settle()
  expect(stateLabel()).toBe('Paused at ply 3')
})

it('selects a historical move with Space once and stays pinned', async () => {
  const cell = [...document.querySelectorAll('[data-move-log] [role="button"]')].find(node => node.textContent === '7g7f')
  key(cell, ' '); await settle()
  expect(get(navigation)).toMatchObject({ matchId: 9, ply: 1 })
  expect(stateLabel()).toBe('Paused at ply 1')
})

it('copies an actual-ply saved link without changing following mode or browser history', async () => {
  const before = location.href
  const push = vi.spyOn(history, 'pushState'), replace = vi.spyOn(history, 'replaceState')
  button('Copy link to this position').click(); await settle()
  const copied = new URL(navigator.clipboard.writeText.mock.calls[0][0])
  expect(copied.searchParams.get('match')).toBe('9')
  expect(copied.searchParams.get('ply')).toBe('3')
  expect(location.href).toBe(before)
  expect(get(navigation)).toMatchObject({ matchId: null, ply: null })
  expect(stateLabel()).toBe('Live')
  expect(push).not.toHaveBeenCalled(); expect(replace).not.toHaveBeenCalled()
  expect(document.querySelector('.viewer-toolbar').textContent).toContain('Link copied.')
})

it('disables playback-speed commands while viewing an archived match', async () => {
  history.replaceState(null, '', '/?view=showcase&match=8&ply=2')
  window.dispatchEvent(new PopStateEvent('popstate')); await settle()
  expect(stateLabel()).toBe('Replay · ply 2')
  const speeds = document.querySelector('[aria-label="Playback speed"]').querySelectorAll('button')
  expect(speeds).toHaveLength(3)
  expect([...speeds].every(node => node.disabled)).toBe(true)
  speeds[2].click(); await settle()
  const { sendShowcaseCommand } = await import('./ws.js')
  expect(sendShowcaseCommand).not.toHaveBeenCalled()
})
