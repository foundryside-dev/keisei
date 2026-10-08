// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import LeagueView from './LeagueView.svelte'
import { leagueEntries, leagueTotals, tournamentStats, historicalLibrary, gauntletResults, focusedEntryId } from '../stores/league.js'
import { trainingState } from '../stores/training.js'

vi.hoisted(() => {
  globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
})

let component
beforeEach(() => {
  leagueEntries.set([{ id: 1, status: 'active', display_name: 'Alpha', elo_rating: 1400, games_played: 0 }])
  leagueTotals.set({ matches: 502, rounds: 70, games: 1506 })
  focusedEntryId.set(null)
  historicalLibrary.set([{ slot_index: 0, target_epoch: 1, actual_epoch: 1, entry_name: 'Founding model', selection_mode: 'log_spaced' }])
  gauntletResults.set([])
  tournamentStats.set({ active_slots: 2, games_per_min: 35, updated_at: '2026-10-08T12:34:56Z' })
  trainingState.set({ config_json: JSON.stringify({ league: { max_active_entries: 7 } }) })
  component = new LeagueView({ target: document.body })
})
afterEach(() => { component.$destroy(); document.body.innerHTML = '' })

it('labels persisted telemetry as a completed round with capacity and timestamp', () => {
  expect(document.body.textContent).toContain('Last completed round')
  expect(document.body.textContent).toContain('2 concurrent slots')
  expect(document.body.textContent).not.toContain('Live ·')
  expect(document.querySelector('.live-dot')).toBeNull()
  expect(document.querySelector('time').dateTime).toBe('2026-10-08T12:34:56Z')
})

it('uses configured pool capacity and exposes historical benchmarks', () => {
  expect(document.body.textContent).toMatch(/1\s*\/\s*7/)
  expect(document.body.textContent).toContain('Founding model')
  expect(document.querySelector('[aria-label="Historical benchmarks"]')).not.toBeNull()
})
