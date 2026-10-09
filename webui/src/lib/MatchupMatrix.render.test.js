// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from 'vitest'
import { tick } from 'svelte'
import MatchupMatrix from './MatchupMatrix.svelte'
import { leagueEntries, headToHeadRaw } from '../stores/league.js'
let component
beforeEach(() => {
  leagueEntries.set([
    { id: 1, display_name: 'Same long player name', created_epoch: 10, status: 'active', elo_rating: 1300 },
    { id: 2, display_name: 'Same long player name', created_epoch: 20, status: 'active', elo_rating: 1200 },
    { id: 3, display_name: 'No games', created_epoch: 30, status: 'active', elo_rating: 1100 },
  ])
  headToHeadRaw.set([{ entry_a_id: 1, entry_b_id: 2, wins_a: 3, wins_b: 1, draws: 2, games: 6 }])
  component = new MatchupMatrix({ target: document.body, props: { totalSlots: 3 } })
})
afterEach(() => { component.$destroy(); document.body.innerHTML = '' })
it('shows each pair once with full identities and accessible matrix names', () => {
  expect(document.querySelectorAll('.record-list li')).toHaveLength(1)
  expect(document.querySelector('.record-list').textContent).toContain('Same long player name · #1 · epoch 10')
  expect(document.querySelector('.record-list').textContent).toContain('3 wins · 1 losses · 2 draws · 6 games')
  expect(document.querySelector('th.col-header').getAttribute('aria-label')).toContain('#1 · epoch 10')
  expect(document.querySelector('.rate-cell').getAttribute('aria-label')).toContain('3 wins, 1 losses, 2 draws')
})
it('filters from the named player perspective and distinguishes no games from no data', async () => {
  const filter = document.querySelector('select')
  filter.value = '2'; filter.dispatchEvent(new Event('change')); await tick()
  expect(document.querySelector('.record-list').textContent).toContain('1 wins · 3 losses · 2 draws')
  expect(document.querySelector('.perspective').textContent).toContain('#2 · epoch 20 perspective')
  filter.value = '3'; filter.dispatchEvent(new Event('change')); await tick()
  expect(document.querySelector('.empty').textContent).toContain('No games for this player filter')
  headToHeadRaw.set([]); await tick()
  expect(document.querySelector('.empty').textContent).toContain('No matchup data yet')
})
it('marks trainer aggregate distinctly and excludes its own snapshots', async () => {
  component.$set({ learnerName: 'Same long player name' }); await tick()
  // Both entries are the trainer snapshots: no synthetic aggregate pair between them.
  expect(document.querySelectorAll('.record-list li')).toHaveLength(1)
  expect([...document.querySelectorAll('option')].some(option => option.textContent.includes('Trainer aggregate'))).toBe(true)
})
