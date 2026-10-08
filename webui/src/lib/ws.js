/**
 * WebSocket client for Keisei spectator dashboard.
 * Connects to /ws, dispatches messages to Svelte stores.
 * Auto-reconnects on disconnect with exponential backoff.
 */

import { writable, get } from 'svelte/store'
import { games, selectedGameId } from '../stores/games.js'
import { metrics, appendMetrics } from '../stores/metrics.js'
import { trainingState } from '../stores/training.js'
import {
  leagueEntries, leagueResults, eloHistory, tournamentStats, diffLeagueEntries,
  historicalLibrary, gauntletResults, leagueTransitions, styleProfilesRaw,
  headToHeadRaw, leagueTotals, entryRecordsRaw, learnerRecentRecordRaw,
} from '../stores/league.js'
import {
  showcaseGame, showcaseMoves, showcaseQueue, sidecarAlive,
  resetShowcaseSelectionOnGameChange,
} from '../stores/showcase.js'

const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
// Brief drops are common (proxy idle-timeouts, GPU stalls, network blips). Hold the
// "reconnecting" banner back this long so a drop+recover within the window is invisible.
// Backoff exceeds this after ~2 failed attempts, so sustained outages still surface.
const DISCONNECT_GRACE_MS = 3000

/** Connection state: 'connecting' | 'connected' | 'reconnecting' */
export const connectionState = writable('connecting')
export const showcaseCommandPending = writable(null)
export const showcaseCommandFeedback = writable(null)

let commandSequence = 0
let commandTimer = null

function finishCommand(kind, message) {
  clearTimeout(commandTimer)
  commandTimer = null
  showcaseCommandPending.set(null)
  showcaseCommandFeedback.set({ kind, message })
}

let ws = null
let reconnectAttempt = 0
let reconnectTimer = null
let reconnectingGraceTimer = null

export function sendShowcaseCommand(message) {
  if (get(showcaseCommandPending)) return false
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showcaseCommandFeedback.set({ kind: 'error', message: 'Not connected to the server. Reconnect before sending a match command.' })
    return false
  }
  const command = { ...message, request_id: `${Date.now()}-${++commandSequence}` }
  showcaseCommandPending.set(command)
  showcaseCommandFeedback.set({ kind: 'pending', message: 'Waiting for the server to confirm…' })
  commandTimer = setTimeout(() => {
    finishCommand('error', 'No confirmation received. Check the match queue before trying again.')
  }, 10000)
  try {
    ws.send(JSON.stringify(command))
    return true
  } catch {
    finishCommand('error', 'The command could not be sent. Check the connection and try again.')
    return false
  }
}

export function connect() {
  if (ws && ws.readyState <= WebSocket.OPEN) return

  ws = new WebSocket(WS_URL)

  ws.onopen = () => {
    console.log('[ws] connected')
    reconnectAttempt = 0
    if (reconnectingGraceTimer != null) {
      clearTimeout(reconnectingGraceTimer)
      reconnectingGraceTimer = null
    }
    connectionState.set('connected')
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      handleMessage(msg)
    } catch (e) {
      console.warn('[ws] failed to parse message:', e)
    }
  }

  ws.onclose = () => {
    if (get(showcaseCommandPending)) {
      finishCommand('error', 'Connection lost before confirmation. Check the match queue after reconnecting.')
    }
    console.log('[ws] disconnected, reconnecting...')
    if (reconnectingGraceTimer == null) {
      reconnectingGraceTimer = setTimeout(() => {
        connectionState.set('reconnecting')
        reconnectingGraceTimer = null
      }, DISCONNECT_GRACE_MS)
    }
    scheduleReconnect()
  }

  ws.onerror = (err) => {
    console.warn('[ws] error', err)
    ws.close()
  }
}

function scheduleReconnect() {
  const base = Math.min(
    RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt),
    RECONNECT_MAX_MS
  )
  // Add jitter: 50-150% of base delay
  const delay = base * (0.5 + Math.random())
  reconnectAttempt++
  reconnectTimer = setTimeout(connect, delay)
}

export function handleMessage(msg) {
  switch (msg.type) {
    case 'init':
      games.set(msg.games || [])
      metrics.set(msg.metrics || [])
      trainingState.set(msg.training_state || null)
      leagueEntries.set(msg.league_entries || [])
      diffLeagueEntries(msg.league_entries || [])
      leagueResults.set(msg.league_results || [])
      leagueTotals.set(msg.league_totals ?? null)
      entryRecordsRaw.set(msg.entry_records || [])
      learnerRecentRecordRaw.set(msg.learner_recent_record ?? null)
      eloHistory.set(msg.elo_history || [])
      historicalLibrary.set(msg.historical_library || [])
      gauntletResults.set(msg.gauntlet_results || [])
      leagueTransitions.set(msg.transitions || [])
      headToHeadRaw.set(msg.head_to_head || [])
      tournamentStats.set(msg.tournament_stats ?? null)
      styleProfilesRaw.set(msg.style_profiles || [])
      if (msg.games?.length > 0) {
        selectedGameId.update(id => id ?? 0)
      }
      // Showcase init (cold-start support)
      if (msg.showcase) {
        if (get(showcaseGame)?.id !== msg.showcase.game?.id) {
          resetShowcaseSelectionOnGameChange(msg.showcase.game?.id ?? null)
        }
        showcaseGame.set(msg.showcase.game || null)
        showcaseMoves.set(msg.showcase.moves || [])
        showcaseQueue.set(msg.showcase.queue || [])
        sidecarAlive.set(msg.showcase.sidecar_alive || false)
      }
      break

    case 'game_update': {
      const snapshots = msg.snapshots || []
      // Merge delta snapshots into existing store (backend sends only changed games)
      games.update(existing => {
        const updated = [...existing]
        for (const snap of snapshots) {
          const idx = updated.findIndex(g => g.game_id === snap.game_id)
          if (idx >= 0) updated[idx] = snap
          else updated.push(snap)
        }
        return updated
      })
      // Auto-switch away from ended games
      selectedGameId.update(id => {
        const current = snapshots.find(g => g.game_id === id)
        if (current && current.is_over) {
          const active = snapshots.find(g => !g.is_over)
          if (active) return active.game_id
        }
        return id
      })
      break
    }

    case 'metrics_update':
      appendMetrics(msg.rows || [])
      break

    case 'training_status':
      if (Object.hasOwn(msg, 'training_state')) {
        trainingState.set(msg.training_state === null ? null : {
          ...msg.training_state,
          ...(Object.hasOwn(msg, 'episodes') ? { episodes: msg.episodes } : {}),
          ...(Object.hasOwn(msg, 'system_stats') ? { system_stats: msg.system_stats } : {}),
        })
        break
      }
      trainingState.update(state => ({
        ...state,
        status: msg.status,
        phase: msg.phase || state?.phase,
        heartbeat_at: msg.heartbeat_at,
        current_epoch: msg.epoch,
        current_step: msg.step,
        episodes: msg.episodes ?? state?.episodes,
        config_json: msg.config_json || state?.config_json,
        display_name: msg.display_name || state?.display_name,
        model_arch: msg.model_arch || state?.model_arch,
        total_epochs: msg.total_epochs ?? state?.total_epochs,
        system_stats: msg.system_stats || state?.system_stats,
        learner_entry_id: Object.hasOwn(msg, 'learner_entry_id') ? msg.learner_entry_id : state?.learner_entry_id,
      }))
      break

    case 'league_update':
      leagueEntries.set(msg.entries || [])
      diffLeagueEntries(msg.entries || [])
      leagueResults.set(msg.results || [])
      leagueTotals.set(msg.league_totals ?? null)
      entryRecordsRaw.set(msg.entry_records || [])
      learnerRecentRecordRaw.set(msg.learner_recent_record ?? null)
      eloHistory.set(msg.elo_history || [])
      historicalLibrary.set(msg.historical_library || [])
      gauntletResults.set(msg.gauntlet_results || [])
      leagueTransitions.set(msg.transitions || [])
      headToHeadRaw.set(msg.head_to_head || [])
      if (Object.hasOwn(msg, 'tournament_stats')) tournamentStats.set(msg.tournament_stats ?? null)
      if (msg.style_profiles) styleProfilesRaw.set(msg.style_profiles)
      break

    case 'showcase_update': {
      const game = msg.game || null
      const gameId = game ? game.id : null
      showcaseGame.set(game)
      // Reset moves when game changes; append within same game
      let gameChanged = false
      showcaseMoves.update(existing => {
        const newMoves = msg.new_moves || []
        if (existing.length > 0 && existing[0].game_id !== gameId) {
          gameChanged = true
          return newMoves
        }
        if (existing.length === 0 && newMoves.length > 0) {
          gameChanged = true
        }
        const maxPly = existing.length > 0 ? existing[existing.length - 1].ply : 0
        const fresh = newMoves.filter(m => m.ply > maxPly)
        return [...existing, ...fresh]
      })
      if (gameChanged) resetShowcaseSelectionOnGameChange(gameId)
      // Persisted game metadata can arrive after the sidecar stops. Liveness
      // is authoritative only in init/showcase_status heartbeat data.
      break
    }

    case 'showcase_status':
      showcaseQueue.set(msg.queue || [])
      sidecarAlive.set(msg.sidecar_alive || false)
      // Keep the completed result available until the next game replaces it.
      // Only clear a stale in-progress board when the server reports no game.
      if (!msg.active_game_id && get(showcaseGame)?.status === 'in_progress') {
        showcaseGame.set(null)
        showcaseMoves.set([])
        resetShowcaseSelectionOnGameChange(null)
      }
      break

    case 'showcase_match_queued':
    case 'showcase_speed_changed':
    case 'showcase_match_cancelled': {
      const pending = get(showcaseCommandPending)
      if (!pending || pending.request_id !== msg.request_id) break
      if (msg.type === 'showcase_speed_changed') {
        showcaseQueue.update(queue => queue.map(q => q.id === msg.queue_id ? { ...q, speed: msg.speed } : q))
        finishCommand('success', 'Playback speed updated.')
      } else if (msg.type === 'showcase_match_cancelled') {
        showcaseQueue.update(queue => queue.filter(q => q.id !== msg.queue_id))
        finishCommand('success', 'Queued match cancelled.')
      } else {
        showcaseQueue.update(queue => queue.some(q => q.id === msg.queue_id) ? queue : [...queue, {
          id: msg.queue_id, entry_id_1: msg.entry_id_1, entry_id_2: msg.entry_id_2,
          speed: msg.speed, status: 'pending',
        }])
        finishCommand('success', 'Match added to the queue.')
      }
      break
    }

    case 'showcase_error':
      if (get(showcaseCommandPending)?.request_id === msg.request_id) {
        finishCommand('error', msg.error || 'The match command was rejected.')
      }
      break

    case 'ping':
      break
  }
}

export function disconnect() {
  if (get(showcaseCommandPending)) finishCommand('error', 'Disconnected before confirmation. Check the match queue after reconnecting.')
  if (reconnectTimer != null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (reconnectingGraceTimer != null) {
    clearTimeout(reconnectingGraceTimer)
    reconnectingGraceTimer = null
  }
  if (ws) {
    ws.onclose = null
    ws.onerror = null
    ws.onmessage = null
    ws.onopen = null
    ws.close()
    ws = null
  }
}
