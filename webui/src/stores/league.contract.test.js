// @vitest-environment jsdom
import { beforeEach, expect, it } from 'vitest'
import { get } from 'svelte/store'
import * as league from './league.js'
import { trainingState } from './training.js'

beforeEach(() => {
  league.leagueEntries.set([])
  league.leagueResults.set([])
  league.leagueTotals?.set(null)
  league.entryRecordsRaw?.set([])
  league.learnerRecentRecordRaw?.set(null)
  trainingState.set(null)
})

it('uses lifetime aggregates even after the recent feed is truncated or cleared', () => {
  league.leagueEntries.set([{ id: 1, status: 'active', elo_rating: 1200 }])
  league.leagueResults.set([{ epoch: 501, entry_a_id: 2, entry_b_id: 3, wins_a: 1 }])
  league.leagueTotals.set({ matches: 502, rounds: 502, games: 507 })
  league.entryRecordsRaw.set([{ entry_id: 1, w: 3, l: 2, d: 1, games: 6 }])
  expect(get(league.entryWLD).get(1)).toEqual({ w: 3, l: 2, d: 1 })
  expect(get(league.leagueStats)).toMatchObject({ totalMatches: 502, totalRounds: 502, totalGames: 507 })
  league.leagueResults.set([])
  expect(get(league.entryWLD).get(1).w).toBe(3)
  expect(get(league.leagueStats).totalMatches).toBe(502)
  league.entryRecordsRaw.set([])
  league.leagueTotals.set({ matches: 0, rounds: 0, games: 0 })
  expect(get(league.entryWLD).size).toBe(0)
  expect(get(league.leagueStats).totalMatches).toBe(0)
})

it('preserves historical totals when all entries are retired', () => {
  league.leagueEntries.set([{ id: 1, status: 'retired', elo_rating: 1200 }])
  league.leagueTotals.set({ matches: 25, rounds: 5, games: 100 })
  expect(get(league.leagueStats)).toMatchObject({ poolSize: 0, totalMatches: 25, topEntry: null })
})

it('uses the same composite rating for ranking, display and the summary', () => {
  const compositeLeader = { id: 1, status: 'active', role: 'dynamic', elo_rating: 1400, elo_dynamic: 900 }
  league.leagueEntries.set([
    compositeLeader,
    { id: 2, status: 'active', role: 'frontier_static', elo_rating: 1200, elo_frontier: 1800 },
  ])
  expect(get(league.leagueRanked)[0].id).toBe(1)
  expect(league.displayElo(compositeLeader)).toEqual({ value: 1400, tag: '' })
  expect(get(league.leagueStats).topEntry.id).toBe(1)
})

it('uses complete learner aggregates even when the recent feed contains other matches', () => {
  league.leagueEntries.set([{ id: 1, status: 'active' }])
  trainingState.set({ learner_entry_id: 1 })
  league.leagueResults.set([
    { epoch: 999, entry_a_id: 8, entry_b_id: 9, wins_a: 100, wins_b: 100, draws: 100 },
  ])
  league.learnerRecentRecordRaw.set({ entry_id: 1, w: 24, l: 13, d: 12, rounds: 10 })
  expect(get(league.learnerRecentRecord)).toEqual({ w: 24, l: 13, d: 12, rounds: 10 })
})

it('hides stale learner aggregates across seat changes and resets', () => {
  league.learnerRecentRecordRaw.set({ entry_id: 1, w: 3, l: 2, d: 1, rounds: 1 })
  expect(get(league.learnerRecentRecord)).toBeNull()
  trainingState.set({ learner_entry_id: 1 })
  expect(get(league.learnerRecentRecord)).toEqual({ w: 3, l: 2, d: 1, rounds: 1 })
  trainingState.set({ learner_entry_id: 2 })
  expect(get(league.learnerRecentRecord)).toBeNull()
  league.learnerRecentRecordRaw.set({ entry_id: 2, w: 0, l: 0, d: 0, rounds: 0 })
  expect(get(league.learnerRecentRecord)).toEqual({ w: 0, l: 0, d: 0, rounds: 0 })
  league.learnerRecentRecordRaw.set(null)
  expect(get(league.learnerRecentRecord)).toBeNull()
})

it('derives capacity from configured tier sizes and an explicit total override', () => {
  trainingState.set({ config_json: JSON.stringify({ league: { frontier: { slots: 2 }, recent: { slots: 3 }, dynamic: { slots: 4 } } }) })
  expect(get(league.leagueCapacity)).toEqual({ total: 9, roles: { frontier_static: 2, recent_fixed: 3, dynamic: 4, historical: 5 } })
  trainingState.set({ config_json: JSON.stringify({ league: { max_active_entries: 7 } }) })
  expect(get(league.leagueCapacity).total).toBe(7)
})
