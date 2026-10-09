// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import LeagueView from './LeagueView.svelte'
import { leagueEntries, headToHeadRaw, gauntletResults, eloHistory, focusedEntryId } from '../stores/league.js'
import { selectEntry, navigation } from '../stores/navigation.js'
import { get } from 'svelte/store'
vi.mock('uplot', () => ({ default: class {} }))
let component
const entries = [
  { id: 1, display_name: 'Alpha', created_epoch: 10, status: 'active', elo_rating: 1300 },
  { id: 2, display_name: 'Zulu', created_epoch: 20, status: 'active', elo_rating: 1200 },
]
const settle = async () => { await tick(); await tick() }
beforeEach(async () => {
  leagueEntries.set(entries)
  headToHeadRaw.set([]); gauntletResults.set([{ id: 1, epoch: 1, wins: 1, losses: 0, draws: 0, historical_slot: 0 }]); eloHistory.set([])
  selectEntry(null); focusedEntryId.set(null)
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ results: [], has_more: false }) })))
  component = new LeagueView({ target: document.body })
  await settle()
})
afterEach(() => { component.$destroy(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
const row = id => document.querySelector(`[data-entry-id="${id}"]`)
it('focuses detail on explicit opening and restores the initiating entry after sorting', async () => {
  row(1).focus(); row(1).click(); await settle()
  expect(get(navigation).entryId).toBe(1)
  expect(document.activeElement.classList.contains('detail-heading')).toBe(true)
  const sort = [...document.querySelectorAll('.sort-btn')].find(button => button.textContent === 'Name')
  sort.click(); await settle()
  document.querySelector('.detail-close-btn').click(); await settle()
  expect(document.activeElement.dataset.entryId).toBe('1')
  expect(get(navigation).entryId).toBe(null)
})
it('Escape restores focus and live updates do not move focus', async () => {
  row(2).focus(); row(2).click(); await settle()
  const heading = document.activeElement
  leagueEntries.set(entries.map(entry => ({ ...entry, elo_rating: entry.elo_rating + 1 }))); await settle()
  expect(document.activeElement).toBe(heading)
  heading.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await settle()
  expect(document.activeElement.dataset.entryId).toBe('2')
})
it('returns to a useful heading if the originating entry disappears', async () => {
  row(1).click(); await settle()
  leagueEntries.set(entries.slice(1)); await settle()
  expect(document.querySelector('.detail-heading').textContent).toContain('Entry #1 unavailable')
  document.querySelector('.detail-close-btn').click(); await settle()
  expect(document.activeElement.textContent).toContain('Elo Leaderboard')
  expect(document.querySelector('[role="status"]').textContent).toContain('no longer in the leaderboard')
})
it('direct entry navigation closes to the heading fallback and retired entries remain identified', async () => {
  leagueEntries.set([...entries, { id: 3, display_name: 'Retired', status: 'retired', elo_rating: 1100 }])
  selectEntry(3); await settle()
  expect(document.querySelector('.retired-status').textContent).toContain('Retired entry')
  document.querySelector('.detail-close-btn').click(); await settle()
  expect(document.activeElement.textContent).toContain('Elo Leaderboard')
  expect(document.querySelector('[role="status"]').textContent).toContain('Focus returned')
})

it('does not move focus during the initial direct-link render', async () => {
  component.$destroy(); document.body.innerHTML = ''
  selectEntry(1)
  component = new LeagueView({ target: document.body })
  await settle()
  expect(document.activeElement).toBe(document.body)
  document.querySelector('.detail-close-btn').click(); await settle()
  expect(document.activeElement.textContent).toContain('Elo Leaderboard')
})
