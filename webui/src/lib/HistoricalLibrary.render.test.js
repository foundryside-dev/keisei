// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import HistoricalLibrary from './HistoricalLibrary.svelte'
import { gauntletResults, historicalLibrary } from '../stores/league.js'
import { trainingState } from '../stores/training.js'
import { gauntletHistory } from '../stores/gauntletHistory.js'
let component
let run = 0
const rows = epoch => [0, 1].map(slot => ({ id: epoch * 2 + slot, epoch, historical_slot: slot, wins: 2, losses: 1, draws: 1 }))
const settle = async () => { await tick(); await new Promise(resolve => setTimeout(resolve, 0)); await tick() }
beforeEach(() => {
  trainingState.set({ started_at: `history-${++run}`, current_epoch: 10 })
  gauntletHistory.setContext(`history-${run}`)
  historicalLibrary.set([])
  gauntletResults.set([10, 9, 8, 7, 6, 5].flatMap(rows))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ results: rows(5), has_more: false, next_before_epoch: 5 }) })))
  component = new HistoricalLibrary({ target: document.body })
})
afterEach(() => { component.$destroy(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
it('labels five evaluation epochs, loads older whole epochs and retains them during live updates', async () => {
  expect(document.body.textContent).toContain('Latest 5 evaluations')
  expect(document.querySelectorAll('.gauntlet-epoch')).toHaveLength(5)
  document.querySelector('.load-history').click(); await settle()
  expect(fetch.mock.calls[0][0]).toContain('before_epoch=6')
  expect(document.querySelectorAll('.gauntlet-epoch')).toHaveLength(6)
  expect(document.querySelectorAll('.gauntlet-row')).toHaveLength(12)
  expect(document.body.textContent).toContain('End of evaluation history')
  gauntletResults.set([11, 10, 9, 8, 7].flatMap(rows)); await tick()
  expect(document.querySelectorAll('.gauntlet-epoch')).toHaveLength(7)
  expect(document.querySelector('.epoch-header').textContent).toContain('11')
})
it('keeps loaded results on a failed request and exposes retry', async () => {
  fetch.mockRejectedValueOnce(new Error('offline'))
  document.querySelector('.load-history').click(); await settle()
  expect(document.querySelectorAll('.gauntlet-epoch')).toHaveLength(5)
  expect(document.querySelector('[role="alert"]').textContent).toContain('still available')
  expect(document.querySelector('.load-history').textContent).toContain('Retry')
  document.querySelector('.load-history').click(); await settle()
  expect(document.querySelectorAll('.gauntlet-epoch')).toHaveLength(6)
})
