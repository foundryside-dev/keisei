// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { get } from 'svelte/store'
import { handleMessage } from './ws.js'
import { games, selectedGameId } from '../stores/games.js'
import { metrics } from '../stores/metrics.js'
import { trainingState } from '../stores/training.js'
import {
  leagueEntries, leagueResults, eloHistory,
  historicalLibrary, gauntletResults, leagueTransitions,
  headToHeadRaw,
  leagueTotals, entryRecordsRaw, learnerRecentRecordRaw, tournamentStats, styleProfilesRaw,
} from '../stores/league.js'
import {
  showcaseGame, showcaseMoves, showcaseQueue, sidecarAlive, showcaseSelectedPly,
} from '../stores/showcase.js'

beforeEach(() => {
  games.set([])
  selectedGameId.set(0) // matches store default (writable(0) in games.js)
  metrics.set([])
  trainingState.set(null)
  leagueEntries.set([])
  leagueResults.set([])
  eloHistory.set([])
  historicalLibrary.set([])
  gauntletResults.set([])
  leagueTransitions.set([])
  headToHeadRaw.set([])
  showcaseGame.set(null)
  showcaseMoves.set([])
  showcaseQueue.set([])
  sidecarAlive.set(false)
})

describe('handleMessage — init', () => {
  it('clears completed-round and profile data when reconnecting to an empty run', () => {
    tournamentStats.set({ active_slots: 4 })
    styleProfilesRaw.set([{ checkpoint_id: 1 }])
    handleMessage({ type: 'init', tournament_stats: null })
    expect(get(tournamentStats)).toBeNull()
    expect(get(styleProfilesRaw)).toEqual([])
  })

  it('clears a removed completed-round snapshot on league updates', () => {
    tournamentStats.set({ active_slots: 4 })
    handleMessage({ type: 'league_update', tournament_stats: null })
    expect(get(tournamentStats)).toBeNull()
  })

  it('allows an explicit null learner identity to clear the previous learner', () => {
    trainingState.set({ learner_entry_id: 12 })
    handleMessage({ type: 'training_status', learner_entry_id: null })
    expect(get(trainingState).learner_entry_id).toBeNull()
  })
  it('clears all trainer metadata when the server reports the training row was removed', () => {
    trainingState.set({ learner_entry_id: 12, display_name: 'Old run', config_json: '{}' })
    handleMessage({ type: 'training_status', training_state: null })
    expect(get(trainingState)).toBeNull()
  })
  it('replaces authoritative trainer metadata while retaining live system and episode fields', () => {
    trainingState.set({ learner_entry_id: 12, display_name: 'Old run', config_json: '{"old":true}', total_epochs: 20 })
    handleMessage({ type: 'training_status', training_state: { learner_entry_id: 13, display_name: '', config_json: '{}', total_epochs: null }, episodes: 7, system_stats: { cpu_percent: 10 } })
    expect(get(trainingState)).toEqual({ learner_entry_id: 13, display_name: '', config_json: '{}', total_epochs: null, episodes: 7, system_stats: { cpu_percent: 10 } })
  })
  it('resets replay selection when reconnecting to a different showcase game', () => {
    showcaseGame.set({ id: 1, status: 'black_wins' })
    showcaseSelectedPly.set(10)
    handleMessage({ type: 'init', showcase: { game: { id: 2, status: 'in_progress' }, moves: [] } })
    expect(get(showcaseSelectedPly)).toBeNull()
  })
  it('loads lifetime aggregates and clears them on a new empty snapshot', () => {
    const totals = { matches: 700, rounds: 80, games: 7000 }
    const records = [{ entry_id: 1, w: 500, l: 300, d: 200, games: 1000 }]
    handleMessage({ type: 'init', league_totals: totals, entry_records: records })
    expect(get(leagueTotals)).toEqual(totals)
    expect(get(entryRecordsRaw)).toEqual(records)
    handleMessage({ type: 'init' })
    expect(get(leagueTotals)).toBeNull()
    expect(get(entryRecordsRaw)).toEqual([])
  })

  it('loads and clears the complete recent learner record on every snapshot', () => {
    const record = { entry_id: 2, w: 7, l: 2, d: 1, rounds: 1 }
    for (const type of ['init', 'league_update']) {
      handleMessage({ type, learner_recent_record: record })
      expect(get(learnerRecentRecordRaw)).toEqual(record)
      handleMessage({ type })
      expect(get(learnerRecentRecordRaw)).toBeNull()
    }
  })

  it('replaces lifetime aggregates on league updates, including empty resets', () => {
    const totals = { matches: 701, rounds: 81, games: 7010 }
    const records = [{ entry_id: 1, w: 507, l: 302, d: 201, games: 1010 }]
    handleMessage({ type: 'league_update', league_totals: totals, entry_records: records })
    expect(get(leagueTotals)).toEqual(totals)
    expect(get(entryRecordsRaw)).toEqual(records)
    handleMessage({ type: 'league_update' })
    expect(get(leagueTotals)).toBeNull()
    expect(get(entryRecordsRaw)).toEqual([])
  })
  it('populates all stores from init message', () => {
    handleMessage({
      type: 'init',
      games: [{ game_id: 0, board: '...' }],
      metrics: [{ id: 1, step: 100 }],
      training_state: { display_name: 'Bot', model_arch: 'resnet' },
    })

    expect(get(games)).toHaveLength(1)
    expect(get(metrics)).toHaveLength(1)
    expect(get(trainingState).display_name).toBe('Bot')
  })

  it('preserves selectedGameId when games are present and ID is already set', () => {
    selectedGameId.set(0)
    handleMessage({
      type: 'init',
      games: [{ game_id: 0 }],
      metrics: [],
      training_state: null,
    })
    expect(get(selectedGameId)).toBe(0)
  })

  it('sets selectedGameId to 0 when games are present and ID is null', () => {
    selectedGameId.set(null)
    handleMessage({
      type: 'init',
      games: [{ game_id: 0 }],
      metrics: [],
      training_state: null,
    })
    expect(get(selectedGameId)).toBe(0)
  })

  it('handles missing fields gracefully', () => {
    handleMessage({ type: 'init' })
    expect(get(games)).toEqual([])
    expect(get(metrics)).toEqual([])
    expect(get(trainingState)).toBeNull()
  })
})

describe('handleMessage — game_update', () => {
  it('replaces games list with snapshots', () => {
    games.set([{ game_id: 0, ply: 10 }])
    handleMessage({
      type: 'game_update',
      snapshots: [{ game_id: 0, ply: 20 }, { game_id: 1, ply: 5 }],
    })
    expect(get(games)).toHaveLength(2)
    expect(get(games)[0].ply).toBe(20)
  })

  it('handles missing snapshots field', () => {
    handleMessage({ type: 'game_update' })
    expect(get(games)).toEqual([])
  })

  it('retains the chosen lane on completion', () => {
    games.set([{game_id:0, is_over:false},{game_id:1,is_over:false}])
    selectedGameId.set(0)
    handleMessage({
      type: 'game_update',
      snapshots: [
        { game_id: 0, is_over: true },
        { game_id: 1, is_over: false },
      ],
    })
    expect(get(selectedGameId)).toBe(0)
  })

  it('stays on ended game when no active game exists', () => {
    selectedGameId.set(0)
    handleMessage({
      type: 'game_update',
      snapshots: [
        { game_id: 0, is_over: true },
        { game_id: 1, is_over: true },
      ],
    })
    expect(get(selectedGameId)).toBe(0)
  })

  it('does not switch when selected game is still in progress', () => {
    selectedGameId.set(0)
    handleMessage({
      type: 'game_update',
      snapshots: [
        { game_id: 0, is_over: false },
        { game_id: 1, is_over: false },
      ],
    })
    expect(get(selectedGameId)).toBe(0)
  })

  it('reconciles an unavailable selection instead of leaving a stale highlight', () => {
    selectedGameId.set(99)
    handleMessage({
      type: 'game_update',
      snapshots: [
        { game_id: 0, is_over: false },
        { game_id: 1, is_over: false },
      ],
    })
    // current is undefined (not found), so no auto-switch
    expect(get(selectedGameId)).toBe(0)
  })
})

describe('handleMessage — metrics_update', () => {
  it('appends new rows to existing metrics', () => {
    metrics.set([{ id: 1, step: 100 }])
    handleMessage({
      type: 'metrics_update',
      rows: [{ id: 2, step: 200 }, { id: 3, step: 300 }],
    })
    expect(get(metrics)).toHaveLength(3)
    expect(get(metrics)[2].id).toBe(3)
  })

  it('handles missing rows field', () => {
    metrics.set([{ id: 1 }])
    handleMessage({ type: 'metrics_update' })
    expect(get(metrics)).toHaveLength(1)
  })
})

describe('handleMessage — training_status', () => {
  it('merges status update into existing state', () => {
    trainingState.set({ display_name: 'Bot', model_arch: 'resnet', status: 'running' })
    handleMessage({
      type: 'training_status',
      status: 'completed',
      heartbeat_at: '2026-04-01T12:00:00Z',
      epoch: 42,
    })
    const state = get(trainingState)
    expect(state.status).toBe('completed')
    expect(state.current_epoch).toBe(42)
    expect(state.display_name).toBe('Bot') // preserved
  })

  it('preserves falsy 0 for episodes via ?? coalescing', () => {
    trainingState.set({ episodes: 5 })
    handleMessage({
      type: 'training_status',
      status: 'running',
      episodes: 0,
    })
    const state = get(trainingState)
    expect(state.episodes).toBe(0)
  })

  it('preserves falsy 0 for total_epochs via ?? coalescing', () => {
    trainingState.set({ total_epochs: 100 })
    handleMessage({
      type: 'training_status',
      status: 'running',
      total_epochs: 0,
    })
    const state = get(trainingState)
    expect(state.total_epochs).toBe(0)
  })

  it('falls back to previous episodes when field is absent (null/undefined)', () => {
    trainingState.set({ episodes: 42 })
    handleMessage({
      type: 'training_status',
      status: 'running',
      // episodes not present → undefined ?? 42 = 42
    })
    expect(get(trainingState).episodes).toBe(42)
  })
})

describe('handleMessage — ping', () => {
  it('does not modify any stores', () => {
    games.set([{ game_id: 0 }])
    metrics.set([{ id: 1 }])
    trainingState.set({ status: 'running' })

    handleMessage({ type: 'ping' })

    expect(get(games)).toHaveLength(1)
    expect(get(metrics)).toHaveLength(1)
    expect(get(trainingState).status).toBe('running')
  })
})

describe('handleMessage — unknown type', () => {
  it('silently ignores unknown message types', () => {
    expect(() => handleMessage({ type: 'unknown_future_type' })).not.toThrow()
  })
})

describe('handleMessage — init with league data', () => {
  it('populates league stores from init message', () => {
    handleMessage({
      type: 'init',
      games: [],
      metrics: [],
      training_state: null,
      league_entries: [{ id: 1, architecture: 'resnet', elo_rating: 1050 }],
      league_results: [{ id: 1, epoch: 5, wins: 3, losses: 1, draws: 1 }],
      elo_history: [{ entry_id: 1, epoch: 5, elo_rating: 1050 }],
    })
    expect(get(leagueEntries)).toHaveLength(1)
    expect(get(leagueResults)).toHaveLength(1)
    expect(get(eloHistory)).toHaveLength(1)
  })

  it('handles init with no league fields gracefully', () => {
    handleMessage({ type: 'init', games: [], metrics: [], training_state: null })
    expect(get(leagueEntries)).toEqual([])
    expect(get(leagueResults)).toEqual([])
    expect(get(eloHistory)).toEqual([])
  })
})

describe('handleMessage — league_update', () => {
  it('replaces all league stores', () => {
    leagueEntries.set([{ id: 99 }])
    handleMessage({
      type: 'league_update',
      entries: [{ id: 1 }, { id: 2 }],
      results: [{ id: 10 }],
      elo_history: [{ entry_id: 1, epoch: 5, elo_rating: 1050 }],
    })
    expect(get(leagueEntries)).toHaveLength(2)
    expect(get(leagueResults)).toHaveLength(1)
    expect(get(eloHistory)).toHaveLength(1)
  })

  it('handles missing fields gracefully', () => {
    handleMessage({ type: 'league_update' })
    expect(get(leagueEntries)).toEqual([])
    expect(get(leagueResults)).toEqual([])
    expect(get(eloHistory)).toEqual([])
  })
})

describe('handleMessage — init with dropped data streams', () => {
  it('populates historicalLibrary from init message', () => {
    handleMessage({
      type: 'init',
      games: [], metrics: [], training_state: null,
      league_entries: [], league_results: [], elo_history: [],
      historical_library: [{ slot_index: 0, entry_name: 'Bot-A' }],
      gauntlet_results: [],
      transitions: [],
    })
    expect(get(historicalLibrary)).toHaveLength(1)
    expect(get(historicalLibrary)[0].slot_index).toBe(0)
  })

  it('populates gauntletResults from init message', () => {
    handleMessage({
      type: 'init',
      games: [], metrics: [], training_state: null,
      league_entries: [], league_results: [], elo_history: [],
      historical_library: [],
      gauntlet_results: [{ id: 1, epoch: 5, wins: 3 }],
      transitions: [],
    })
    expect(get(gauntletResults)).toHaveLength(1)
    expect(get(gauntletResults)[0].epoch).toBe(5)
  })

  it('populates leagueTransitions from msg.transitions key', () => {
    handleMessage({
      type: 'init',
      games: [], metrics: [], training_state: null,
      league_entries: [], league_results: [], elo_history: [],
      historical_library: [],
      gauntlet_results: [],
      transitions: [{ id: 1, from_role: 'dynamic', to_role: 'frontier_static' }],
    })
    expect(get(leagueTransitions)).toHaveLength(1)
    expect(get(leagueTransitions)[0].from_role).toBe('dynamic')
  })

  it('defaults new stores to [] when keys are absent', () => {
    handleMessage({ type: 'init', games: [], metrics: [], training_state: null })
    expect(get(historicalLibrary)).toEqual([])
    expect(get(gauntletResults)).toEqual([])
    expect(get(leagueTransitions)).toEqual([])
  })
})

describe('handleMessage — league_update with dropped data streams', () => {
  it('populates all 3 new stores from league_update', () => {
    handleMessage({
      type: 'league_update',
      entries: [], results: [], elo_history: [],
      historical_library: [{ slot_index: 0 }],
      gauntlet_results: [{ id: 1 }],
      transitions: [{ id: 1 }],
    })
    expect(get(historicalLibrary)).toHaveLength(1)
    expect(get(gauntletResults)).toHaveLength(1)
    expect(get(leagueTransitions)).toHaveLength(1)
  })

  it('defaults new stores to [] when keys are absent in league_update', () => {
    handleMessage({ type: 'league_update' })
    expect(get(historicalLibrary)).toEqual([])
    expect(get(gauntletResults)).toEqual([])
    expect(get(leagueTransitions)).toEqual([])
  })
})

describe('handleMessage — showcase_update', () => {
  it('clears the previous board history when a new game arrives before its first move', () => {
    showcaseGame.set({ id: 10, status: 'black_wins' })
    showcaseMoves.set([{ game_id: 10, ply: 1 }])
    handleMessage({ type: 'showcase_update', game: { id: 11, status: 'in_progress' }, new_moves: [] })
    expect(get(showcaseMoves)).toEqual([])
  })
  it('sets game and appends moves within the same game', () => {
    showcaseMoves.set([{ ply: 1, game_id: 10 }])
    handleMessage({
      type: 'showcase_update',
      game: { id: 10, status: 'in_progress' },
      new_moves: [{ ply: 2, game_id: 10 }],
    })
    expect(get(showcaseGame)).toEqual({ id: 10, status: 'in_progress' })
    expect(get(showcaseMoves)).toHaveLength(2)
    expect(get(showcaseMoves)[1].ply).toBe(2)
  })

  it('resets moves when game_id changes (new game)', () => {
    showcaseMoves.set([{ ply: 1, game_id: 10 }, { ply: 2, game_id: 10 }])
    handleMessage({
      type: 'showcase_update',
      game: { id: 20, status: 'in_progress' },
      new_moves: [{ ply: 1, game_id: 20 }],
    })
    expect(get(showcaseGame).id).toBe(20)
    expect(get(showcaseMoves)).toHaveLength(1)
    expect(get(showcaseMoves)[0].game_id).toBe(20)
  })

  it('deduplicates moves already seen', () => {
    showcaseMoves.set([{ ply: 1, game_id: 10 }, { ply: 2, game_id: 10 }])
    handleMessage({
      type: 'showcase_update',
      game: { id: 10, status: 'in_progress' },
      new_moves: [{ ply: 2, game_id: 10 }, { ply: 3, game_id: 10 }],
    })
    expect(get(showcaseMoves)).toHaveLength(3)
    expect(get(showcaseMoves)[2].ply).toBe(3)
  })

  it('does not override an offline heartbeat when receiving persisted game metadata', () => {
    sidecarAlive.set(false)
    handleMessage({
      type: 'showcase_update',
      game: { id: 10, status: 'in_progress' },
      new_moves: [],
    })
    expect(get(sidecarAlive)).toBe(false)
  })
})

describe('handleMessage — showcase_status', () => {
  it('retains the final result and board when no active game remains', () => {
    showcaseGame.set({ id: 10, status: 'black_wins' })
    showcaseMoves.set([{ game_id: 10, ply: 99 }])
    handleMessage({ type: 'showcase_status', active_game_id: null, queue: [], sidecar_alive: false })
    expect(get(showcaseGame)?.status).toBe('black_wins')
    expect(get(showcaseMoves)).toHaveLength(1)
    expect(get(sidecarAlive)).toBe(false)
  })
  it('updates queue and sidecar status', () => {
    handleMessage({
      type: 'showcase_status',
      queue: [{ id: 1, status: 'pending' }],
      active_game_id: 10,
      sidecar_alive: true,
    })
    expect(get(showcaseQueue)).toHaveLength(1)
    expect(get(sidecarAlive)).toBe(true)
  })

  it('clears game and moves when active_game_id is null (game ended)', () => {
    showcaseGame.set({ id: 10, status: 'in_progress' })
    showcaseMoves.set([{ ply: 1, game_id: 10 }, { ply: 2, game_id: 10 }])
    handleMessage({
      type: 'showcase_status',
      queue: [],
      active_game_id: null,
      sidecar_alive: true,
    })
    expect(get(showcaseGame)).toBeNull()
    expect(get(showcaseMoves)).toEqual([])
  })

  it('preserves game and moves when active_game_id is present', () => {
    showcaseGame.set({ id: 10, status: 'in_progress' })
    showcaseMoves.set([{ ply: 1, game_id: 10 }])
    handleMessage({
      type: 'showcase_status',
      queue: [],
      active_game_id: 10,
      sidecar_alive: true,
    })
    expect(get(showcaseGame)).not.toBeNull()
    expect(get(showcaseMoves)).toHaveLength(1)
  })
})
