import { expect, it, vi } from 'vitest'
import { get } from 'svelte/store'
import { createGauntletHistory } from './gauntletHistory.js'
const rows = epoch => [0, 1].map(slot => ({ id: epoch * 2 + slot, epoch, historical_slot: slot, wins: 2, losses: 1, draws: 1 }))
const response = (results, has_more = false) => ({ ok: true, json: async () => ({ results, next_before_epoch: results.at(-1)?.epoch ?? null, has_more }) })

it('starts with 5 distinct epochs, preserves complete slot rows and pages beyond the live 50 window', async () => {
  const fetcher = vi.fn(async url => {
    const before = Number(new URL(url, 'http://localhost').searchParams.get('before_epoch'))
    const epochs = Array.from({ length: 5 }, (_, i) => before - 1 - i).filter(e => e > 0)
    return response(epochs.flatMap(rows), epochs.at(-1) > 1)
  })
  const history = createGauntletHistory(fetcher)
  history.setLive(Array.from({ length: 50 }, (_, i) => 51 - i).flatMap(rows))
  expect(get(history).epochs.map(([epoch]) => epoch)).toEqual([51, 50, 49, 48, 47])
  for (let i = 0; i < 10; i++) await history.loadOlder()
  expect(get(history).epochs).toHaveLength(51)
  expect(get(history).epochs.every(([, results]) => results.length === 2)).toBe(true)
  expect(get(history).hasMore).toBe(false)
  expect(fetcher.mock.calls.at(-1)[0]).toContain('before_epoch=2')
})

it('keeps older pages and deduplicates result IDs when live epochs arrive', async () => {
  const history = createGauntletHistory(async () => response(rows(5)))
  history.setLive([10, 9, 8, 7, 6].flatMap(rows))
  await history.loadOlder()
  history.setLive([11, 10, 9, 8, 7].flatMap(rows))
  expect(get(history).epochs.map(([e]) => e)).toEqual([11, 10, 9, 8, 7, 6, 5])
  expect(get(history).epochs.flatMap(([, r]) => r)).toHaveLength(14)
})

it('offers retry without erasing loaded results after failure, and handles empty history', async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(response([], false))
  const history = createGauntletHistory(fetcher)
  history.setLive(rows(6))
  await history.loadOlder()
  expect(get(history).error).toContain('still available')
  expect(get(history).epochs).toHaveLength(1)
  await history.loadOlder()
  expect(get(history)).toMatchObject({ loading: false, error: '', hasMore: false })
  const empty = createGauntletHistory(async () => response([]))
  await empty.loadOlder()
  expect(get(empty)).toMatchObject({ epochs: [], hasMore: false })
})

it('rejects a late response after run context changes', async () => {
  let resolve
  const fetcher = vi.fn(() => new Promise(done => { resolve = done }))
  const history = createGauntletHistory(fetcher)
  history.setContext('run-a')
  history.setLive(rows(10))
  const pending = history.loadOlder()
  history.setContext('run-b')
  history.setLive(rows(1))
  resolve(response(rows(9)))
  await pending
  expect(get(history).epochs.map(([e]) => e)).toEqual([1])
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
})
