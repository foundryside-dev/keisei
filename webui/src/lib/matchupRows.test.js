import { expect, it } from 'vitest'
import { matchupIdentity, matchupRows } from './matchupRows.js'

const players = [{ id: 1, display_name: 'A', created_epoch: 1 }, { id: 2, display_name: 'A', created_epoch: 2 }]
const recordFor = (a, b) => a === 1 && b === 2 ? { w: 3, l: 1, d: 2, total: 6 } : a === 2 && b === 1 ? { w: 1, l: 3, d: 2, total: 6 } : null
it('emits each unordered pair once and reverses wins/losses for the selected player', () => {
  expect(matchupRows(players, recordFor)).toMatchObject([{ player: { id: 1 }, opponent: { id: 2 }, w: 3, l: 1, d: 2, total: 6 }])
  expect(matchupRows(players, recordFor, '2')).toMatchObject([{ player: { id: 2 }, opponent: { id: 1 }, w: 1, l: 3, d: 2, total: 6 }])
  expect(matchupRows(players, recordFor, 'missing')).toEqual([])
})
it('includes full name, stable identity and epoch even when names duplicate', () => {
  expect(players.map(matchupIdentity)).toEqual(['A · #1 · epoch 1', 'A · #2 · epoch 2'])
})
