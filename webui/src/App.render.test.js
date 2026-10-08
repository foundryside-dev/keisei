// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import App from './App.svelte'
import { leagueEntries, leagueResults, learnerRecentRecordRaw } from './stores/league.js'
import { trainingState } from './stores/training.js'
import { activeTab } from './stores/navigation.js'

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
  activeTab.set('training')
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
