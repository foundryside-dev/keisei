// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import App from './App.svelte'
import { leagueEntries, leagueResults, learnerRecentRecordRaw } from './stores/league.js'
import { trainingState } from './stores/training.js'
import { games, selectedGameId } from './stores/games.js'
import { metrics } from './stores/metrics.js'
import { get } from 'svelte/store'

vi.mock('svelte', async () => import('svelte/internal'))
vi.mock('uplot', () => ({ default: class { setData() {} redraw() {} destroy() {} setSize() {} } }))

vi.hoisted(() => {
  globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
})

vi.mock('./lib/ws.js', async () => {
  const { writable } = await import('svelte/store')
  return { connect: vi.fn(), disconnect: vi.fn(), sendShowcaseCommand: vi.fn(), connectionState: writable('connected'), showcaseCommandPending: writable(null), showcaseCommandFeedback: writable(null) }
})
let component
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
  history.replaceState(null, '', '/?view=training')
  window.dispatchEvent(new PopStateEvent('popstate'))
  games.set([]); metrics.set([])
  trainingState.set({ learner_entry_id: 2, display_name: 'Learner' })
  leagueEntries.set([{ id: 2, display_name: 'Learner', status: 'active', role: 'dynamic', elo_rating: 1200 }])
  leagueResults.set([
    { epoch: 5, entry_a_id: 1, entry_b_id: 2, wins_a: 2, wins_b: 7, draws: 1 },
    { epoch: 5, entry_a_id: 3, entry_b_id: 4, wins_a: 20, wins_b: 4, draws: 9 },
  ])
  learnerRecentRecordRaw.set({ entry_id: 2, w: 7, l: 2, d: 1, rounds: 1 })
  component = new App({ target: document.body })
})
afterEach(() => { component.$destroy(); document.body.innerHTML = ''; vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('shows the learner perspective and excludes unrelated recent matches', async () => {
  await tick()
  const card = document.querySelector('.player-panel')
  expect(card.textContent).toContain('7 / 2 / 1')
  expect(card.textContent).toContain('Recent W/L/D')
})


const trainingLane = id => ({
  game_id: id, board_json: '[]', hands_json: '{}', move_history_json: '[]',
  ply: id + 1, current_player: 'black', result: 'in_progress', is_over: false,
})

it('makes every loaded lane selectable including lane 32 and keeps selected highlights consistent', async () => {
  games.set(Array.from({ length: 32 }, (_, id) => trainingLane(id)))
  await tick(); await tick()
  const desktop = document.querySelector('.desktop-games')
  const compact = document.querySelector('.compact-games')
  expect(desktop.querySelectorAll('.thumbnail')).toHaveLength(32)
  expect(compact.querySelectorAll('.thumbnail')).toHaveLength(32)
  desktop.querySelector('[aria-label^="Game 32,"]').click()
  await tick()
  expect(get(selectedGameId)).toBe(31)
  expect(document.querySelector('.game-info').textContent).toContain('Game 32')
  expect(desktop.querySelectorAll('[aria-pressed="true"]')).toHaveLength(1)
  expect(compact.querySelector('[aria-pressed="true"]').getAttribute('aria-label')).toMatch(/^Game 32,/)
})

it('places player identity and board before the selector and metrics in reading order with details initially closed', async () => {
  games.set([trainingLane(0)])
  await tick(); await tick()
  const player = document.querySelector('.player-panel')
  const board = document.querySelector('#game-panel')
  const selector = document.querySelector('.thumbnail-panel')
  const metricsPanel = document.querySelector('.metrics-panel')
  expect(player.compareDocumentPosition(board) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(board.compareDocumentPosition(selector) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(selector.compareDocumentPosition(metricsPanel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect([...document.querySelectorAll('.player-details, .run-details, .metrics-panel, .compact-games')].every(details => !details.open)).toBe(true)
  const playerDetails = player.querySelector('details')
  playerDetails.open = true
  metricsPanel.open = true
  trainingState.update(state => ({ ...state, current_step: 100 }))
  await tick(); await tick()
  expect(playerDetails.open).toBe(true)
  expect(metricsPanel.open).toBe(true)
})

it('shows a consistent empty viewer and selector when all lanes disappear', async () => {
  games.set([trainingLane(0), trainingLane(1)])
  selectedGameId.set(1)
  await tick()
  games.set([])
  await tick(); await tick()
  expect(get(selectedGameId)).toBeNull()
  expect(document.querySelector('.no-game').textContent).toContain('Waiting for game data')
  expect(document.querySelector('.compact-games summary').textContent).toContain('Choose game (0) · No lane')
  expect(document.querySelectorAll('.thumbnail')).toHaveLength(0)
})
