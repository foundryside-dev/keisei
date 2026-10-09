import { describe, it, expect, beforeEach } from 'vitest'
import { get } from 'svelte/store'
import { games, selectedGameId, selectedGame, selectedOpponent, laneAnnouncement } from './games.js'
import { leagueEntries } from './league.js'

beforeEach(() => {
  games.set([])
  selectedGameId.set(0)
  leagueEntries.set([])
  laneAnnouncement.set({ message: '', revision: 0 })
})

describe('games store', () => {
  it('starts empty', () => {
    expect(get(games)).toEqual([])
  })
})

describe('selectedGame derived store', () => {
  const gameList = [
    { game_id: 0, board: '...', ply: 10 },
    { game_id: 1, board: '...', ply: 20 },
    { game_id: 2, board: '...', ply: 30 },
  ]

  it('returns null when no games exist', () => {
    expect(get(selectedGame)).toBeNull()
  })

  it('selects game by selectedGameId', () => {
    games.set(gameList)
    selectedGameId.set(1)
    expect(get(selectedGame).game_id).toBe(1)
    expect(get(selectedGame).ply).toBe(20)
  })

  it('falls back to first game when selectedGameId has no match', () => {
    games.set(gameList)
    selectedGameId.set(999)
    expect(get(selectedGame).game_id).toBe(0)
  })

  it('returns null when games array is empty and ID is set', () => {
    selectedGameId.set(5)
    expect(get(selectedGame)).toBeNull()
  })

  it('updates reactively when games list changes', () => {
    games.set(gameList)
    selectedGameId.set(2)
    expect(get(selectedGame).ply).toBe(30)

    // Replace game list — game_id 2 now has different data
    games.set([{ game_id: 2, board: 'new', ply: 50 }])
    expect(get(selectedGame).ply).toBe(50)
  })
})

describe('selectedOpponent derived store', () => {
  it('returns null when game has no opponent_id', () => {
    games.set([{ game_id: 0, opponent_id: null }])
    selectedGameId.set(0)
    expect(get(selectedOpponent)).toBeNull()
  })

  it('returns null when no league entries exist', () => {
    games.set([{ game_id: 0, opponent_id: 5 }])
    selectedGameId.set(0)
    expect(get(selectedOpponent)).toBeNull()
  })

  it('returns opponent entry when opponent_id matches a league entry', () => {
    leagueEntries.set([
      { id: 5, architecture: 'transformer_ep00008', elo_rating: 1180, games_played: 124, display_name: 'transformer_ep00008', created_epoch: 8, flavour_facts: [], model_params: {}, created_at: '2026-04-01T00:00:00Z' },
    ])
    games.set([{ game_id: 0, opponent_id: 5 }])
    selectedGameId.set(0)
    const opp = get(selectedOpponent)
    expect(opp).toEqual({
      display_name: 'transformer_ep00008',
      architecture: 'transformer_ep00008',
      elo_rating: 1180,
      games_played: 124,
      created_epoch: 8,
      flavour_facts: [],
      model_params: {},
      created_at: '2026-04-01T00:00:00Z',
    })
  })
})


describe('training lane custody', () => {
  it('retains the chosen lane when its game completes even when another lane is active', () => {
    games.set([{ game_id: 17, ply: 20, is_over: false }, { game_id: 0, ply: 5, is_over: false }])
    selectedGameId.set(17)
    games.set([{ game_id: 17, ply: 21, is_over: true }, { game_id: 0, ply: 6, is_over: false }])
    expect(get(selectedGameId)).toBe(17)
    expect(get(selectedGame)).toMatchObject({ game_id: 17, is_over: true })
  })

  it('reconciles removal to the lowest active lane and announces the new consistent selection', () => {
    games.set([{ game_id: 17 }, { game_id: 8 }, { game_id: 3, is_over: true }, { game_id: 5 }])
    selectedGameId.set(17)
    games.set([{ game_id: 8 }, { game_id: 3, is_over: true }, { game_id: 5 }])
    expect(get(selectedGameId)).toBe(5)
    expect(get(selectedGame).game_id).toBe(5)
    expect(get(laneAnnouncement).message).toBe('Lane 18 is unavailable. Selected lane 6.')
  })

  it('chooses the lowest available finished lane if no active lane remains, then clears an empty set', () => {
    games.set([{ game_id: 9, is_over: true }, { game_id: 2, is_over: true }])
    selectedGameId.set(9)
    games.set([{ game_id: 5, is_over: true }, { game_id: 2, is_over: true }])
    expect(get(selectedGameId)).toBe(2)
    games.set([])
    expect(get(selectedGameId)).toBeNull()
    expect(get(selectedGame)).toBeNull()
    expect(get(laneAnnouncement).message).toBe('No training lanes available.')
  })

  it('advances a replacement game in the same lane with a concise status', () => {
    games.set([{ game_id: 17, ply: 50, is_over: true }])
    selectedGameId.set(17)
    games.set([{ game_id: 17, ply: 1, is_over: false }])
    expect(get(selectedGameId)).toBe(17)
    expect(get(selectedGame).ply).toBe(1)
    expect(get(laneAnnouncement).message).toBe('New game in lane 18')
  })
})
