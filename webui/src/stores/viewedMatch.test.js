import { describe, it, expect, vi, afterEach } from 'vitest'
import { writable, get } from 'svelte/store'
import { createViewedMatch } from './viewedMatch.js'

const adapters = []
afterEach(() => adapters.splice(0).forEach(adapter => adapter.destroy()))
const route = (matchId = null, ply = null) => ({ view: 'showcase', matchId, ply, error: '' })
const game = (id, status = 'in_progress') => ({ id, status })
const moves = (id, plies) => plies.map(ply => ({ game_id: id, ply, board_json: '[]' }))
const response = (id, plies, status = 'black_wins') => ({ ok: true, json: async () => ({ game: game(id, status), moves: moves(id, plies) }) })
async function flush() { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
function setup(initial = route(), fetchGame = vi.fn().mockResolvedValue(response(1, [1, 2, 3]))) {
  const navigationStore = writable(initial), liveGameStore = writable(null), liveMovesStore = writable([])
  const adapter = createViewedMatch({ navigationStore, liveGameStore, liveMovesStore, fetchGame })
  adapters.push(adapter)
  return { adapter, navigationStore, liveGameStore, liveMovesStore, fetchGame }
}

describe('viewed match identity and positions', () => {
  it('follows the latest live feed without requests or mixing moves between game IDs', () => {
    const s = setup()
    s.liveGameStore.set(game(1)); s.liveMovesStore.set(moves(1, [1, 2]))
    expect(get(s.adapter)).toMatchObject({ game: game(1), displayedMove: { ply: 2 }, following: true, explicitMatch: false })
    s.liveGameStore.set(game(2))
    expect(get(s.adapter).moves).toEqual([])
    s.liveMovesStore.set(moves(2, [1]))
    expect(get(s.adapter).displayedMove.ply).toBe(1)
    expect(s.fetchGame).not.toHaveBeenCalled()
  })
  it('loads a pinned archive using actual ply, never overwritten by another live game', async () => {
    const s = setup(route(1, 3), vi.fn().mockResolvedValue(response(1, [1, 3, 5])))
    expect(get(s.adapter).loading).toBe(true)
    await flush()
    expect(get(s.adapter)).toMatchObject({ archived: true, following: false, selectedIndex: 1, displayedMove: { ply: 3 } })
    s.liveGameStore.set(game(99)); s.liveMovesStore.set(moves(99, [1]))
    expect(get(s.adapter).game.id).toBe(1)
  })
  it('follows only an explicit match tail and retains identity when the feed advances', async () => {
    const s = setup(route(1), vi.fn().mockResolvedValue(response(1, [1, 2])))
    await flush()
    s.liveGameStore.set(game(1)); s.liveMovesStore.set(moves(1, [1, 2, 3]))
    expect(get(s.adapter).displayedMove.ply).toBe(3)
    s.liveGameStore.set(game(2)); s.liveMovesStore.set(moves(2, [1]))
    await flush()
    expect(get(s.adapter)).toMatchObject({ game: { id: 1 }, archived: true })
  })
  it('pins even the current tail across append and only resumes on explicit null ply', async () => {
    const s = setup(route(1, 3))
    await flush()
    s.liveGameStore.set(game(1)); s.liveMovesStore.set(moves(1, [1, 2, 3]))
    expect(get(s.adapter)).toMatchObject({ following: false, selectedIndex: 2 })
    s.liveMovesStore.set(moves(1, [1, 2, 3, 4]))
    expect(get(s.adapter).displayedMove.ply).toBe(3)
    s.navigationStore.set(route(1))
    expect(get(s.adapter)).toMatchObject({ following: true, displayedMove: { ply: 4 } })
    expect(s.fetchGame).toHaveBeenCalledTimes(1)
  })
  it('visibly clamps outside the stored range and rejects missing interior plies', async () => {
    const s = setup(route(1, 99), vi.fn().mockResolvedValue(response(1, [1, 3])))
    await flush()
    expect(get(s.adapter)).toMatchObject({ displayedMove: { ply: 3 }, following: false, status: expect.stringMatching(/outside.*stored ply 3/) })
    s.navigationStore.set(route(1, 0))
    expect(get(s.adapter).displayedMove.ply).toBe(1)
    s.navigationStore.set(route(1, 2))
    expect(get(s.adapter)).toMatchObject({ game: null, error: expect.stringMatching(/not stored/) })
  })
  it('ignores late previous-match responses even when the transport ignores abort', async () => {
    const pending = []
    const s = setup(route(1), vi.fn().mockImplementation((url, options) => new Promise(resolve => pending.push({ resolve, signal: options.signal }))))
    s.navigationStore.set(route(2, 2))
    expect(pending[0].signal.aborted).toBe(true)
    pending[1].resolve(response(2, [1, 2])); await flush()
    pending[0].resolve(response(1, [1, 2, 3])); await flush()
    expect(get(s.adapter)).toMatchObject({ game: { id: 2 }, displayedMove: { ply: 2 } })
  })
  it('does not replace a newer live tail with an older API snapshot', async () => {
    let resolve
    const s = setup(route(1), vi.fn().mockImplementation(() => new Promise(done => { resolve = done })))
    s.liveGameStore.set(game(1)); s.liveMovesStore.set(moves(1, [1, 2, 3, 4]))
    resolve(response(1, [1, 2], 'in_progress')); await flush()
    expect(get(s.adapter).displayedMove.ply).toBe(4)
  })
  it('surfaces absent matches, retains identity and supports retry', async () => {
    const fetchGame = vi.fn().mockResolvedValueOnce({ ok: false, status: 404 }).mockResolvedValueOnce(response(1, [1]))
    const s = setup(route(1), fetchGame)
    s.liveGameStore.set(game(2)); s.liveMovesStore.set(moves(2, [1])); await flush()
    expect(get(s.adapter)).toMatchObject({ game: null, error: expect.stringMatching(/unavailable/) })
    await s.adapter.retry()
    expect(get(s.adapter)).toMatchObject({ game: { id: 1 }, error: '' })
  })
  it('suppresses arbitrary live fallback for malformed links', () => {
    const s = setup({ ...route(), error: 'Invalid match link' })
    s.liveGameStore.set(game(2)); s.liveMovesStore.set(moves(2, [1]))
    expect(get(s.adapter)).toMatchObject({ game: null, error: 'Invalid match link' })
    expect(s.fetchGame).not.toHaveBeenCalled()
  })
  it('handles no-move matches and requested positions without inventing a board', async () => {
    const s = setup(route(1, 1), vi.fn().mockResolvedValue(response(1, [])))
    await flush()
    expect(get(s.adapter)).toMatchObject({ game: null, error: expect.stringMatching(/No moves/) })
    s.navigationStore.set(route(1))
    expect(get(s.adapter)).toMatchObject({ game: { id: 1 }, moves: [], error: '' })
  })
  it.each([
    { game: game(2), moves: moves(2, [1]) },
    { game: game(1), moves: moves(1, [1, 1]) },
    { game: game(1), moves: moves(2, [1]) },
  ])('rejects inconsistent archived data', async payload => {
    const s = setup(route(1), vi.fn().mockResolvedValue({ ok: true, json: async () => payload }))
    await flush()
    expect(get(s.adapter).error).not.toBe('')
    expect(get(s.adapter).game).toBeNull()
  })
  it('aborts and ignores pending work after destroy', async () => {
    let resolve, signal
    const s = setup(route(1), vi.fn().mockImplementation((url, options) => {
      signal = options.signal
      return new Promise(done => { resolve = done })
    }))
    s.adapter.destroy()
    expect(signal.aborted).toBe(true)
    resolve(response(1, [1])); await flush()
    expect(get(s.adapter).game).toBeNull()
  })
})

it('clamps an unplayed ply once and keeps the paused position stable across live appends', async () => {
  const s = setup(route(1, 99), vi.fn().mockResolvedValue(response(1, [1, 2, 3], 'in_progress')))
  await flush()
  s.liveGameStore.set(game(1)); s.liveMovesStore.set(moves(1, [1, 2, 3]))
  expect(get(s.adapter)).toMatchObject({ following: false, displayedMove: { ply: 3 } })
  s.liveMovesStore.set(moves(1, [1, 2, 3, 4]))
  expect(get(s.adapter)).toMatchObject({ following: false, displayedMove: { ply: 3 }, status: expect.stringContaining('stored ply 3') })
  s.navigationStore.set(route(1, 100))
  expect(get(s.adapter).displayedMove.ply).toBe(4)
  s.navigationStore.set(route(1))
  expect(get(s.adapter)).toMatchObject({ following: true, displayedMove: { ply: 4 } })
})
