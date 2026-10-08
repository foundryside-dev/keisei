// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from 'vitest'
import { tick } from 'svelte'
import LeagueTable from './LeagueTable.svelte'
import { leagueEntries, leagueResults, focusedEntryId } from '../stores/league.js'

let component
beforeEach(() => {
  leagueEntries.set([
    { id: 1, status: 'active', role: 'frontier_static', display_name: 'Alpha', elo_rating: 1400, elo_frontier: 1400, games_played: 30 },
    { id: 2, status: 'active', role: 'frontier_static', display_name: 'Zulu', elo_rating: 1100, elo_frontier: 1100, games_played: 40 },
  ])
  leagueResults.set([])
  focusedEntryId.set(null)
  component = new LeagueTable({ target: document.body })
})
afterEach(() => { component.$destroy(); document.body.innerHTML = '' })

const rows = () => [...document.querySelectorAll('tbody tr[aria-label]')]
const click = async (text) => {
  [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text).click()
  await tick()
}

it('preserves league rank and champion when sorting by another column', async () => {
  await click('Name')
  expect(rows()[0].textContent).toContain('Zulu')
  expect(rows()[0].getAttribute('aria-label')).toMatch(/^Rank 2:/)
  expect(rows()[0].textContent).not.toContain('champion')
  expect(rows()[1].textContent).toContain('champion')
})

it('applies the selected sort within grouped rows too', async () => {
  await click('Grouped')
  await click('Name')
  expect(rows().map(row => row.getAttribute('aria-label'))).toEqual([
    expect.stringMatching(/^Rank 2: Zulu/), expect.stringMatching(/^Rank 1: Alpha/),
  ])
})

it('uses configured role capacity rather than hardcoded placeholder counts', async () => {
  component.$set({ totalSlots: 7, roleCapacities: { frontier_static: 2, recent_fixed: 2, dynamic: 3, historical: 1 } })
  await tick()
  await click('Grouped')
  expect(document.querySelector('.group-heading').textContent).toContain('2/2')
  expect(document.querySelectorAll('.placeholder-row')).toHaveLength(0)
})
