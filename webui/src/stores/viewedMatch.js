import { writable } from 'svelte/store'

function validPly(value) {
  return Number.isSafeInteger(value) && value >= 0
}

function orderedMoves(moves, gameId) {
  if (!Array.isArray(moves)) throw new Error('Invalid match response')
  const seen = new Set()
  for (const move of moves) {
    if (!move || !validPly(move.ply) || seen.has(move.ply) || (move.game_id != null && Number(move.game_id) !== gameId)) {
      throw new Error('Invalid stored match positions')
    }
    seen.add(move.ply)
  }
  return [...moves].sort((a, b) => a.ply - b.ply)
}

/** Read-only displayed-match adapter. It never mutates live-feed or URL stores. */
export function createViewedMatch({ navigationStore, liveGameStore, liveMovesStore, fetchGame = (url, options) => fetch(url, options) }) {
  const state = writable({ game: null, moves: [], displayedMove: null, selectedIndex: null, following: true, explicitMatch: false, archived: false, loading: false, error: '', canRetry: false, status: '' })
  let route = { view: 'training', matchId: null, ply: null, error: '' }
  let liveGame = null
  let liveMoves = []
  let cached = null
  let loading = false
  let requestError = ''
  let controller = null
  let generation = 0
  let destroyed = false
  let clampedPly = null

  function matchingLive() {
    return liveGame && Number(liveGame.id) === route.matchId
  }
  function movesForLiveGame() {
    if (!liveGame || liveMoves.some(move => move.game_id != null && Number(move.game_id) !== Number(liveGame.id))) return []
    return liveMoves
  }
  function captureLive() {
    if (!matchingLive()) return
    const moves = movesForLiveGame()
    // Metadata and move stores update separately. Preserve this match's moves
    // while a new feed identity is being installed instead of mixing games.
    if (moves.length || !cached) cached = { game: liveGame, moves }
    else cached = { ...cached, game: liveGame }
  }
  function publish() {
    if (destroyed) return
    const explicitMatch = route.matchId != null
    const live = matchingLive()
    let game = explicitMatch ? (live ? liveGame : cached?.game || null) : liveGame
    let moves = explicitMatch ? (live ? (movesForLiveGame().length ? movesForLiveGame() : cached?.moves || []) : cached?.moves || []) : movesForLiveGame()
    let error = route.error || (!live && requestError) || ''
    let status = ''
    let selectedIndex = null
    const following = route.ply == null
    if (!error && route.ply != null && moves.length) {
      const requestedPly = clampedPly ?? route.ply
      selectedIndex = moves.findIndex(move => move.ply === requestedPly)
      if (selectedIndex < 0) {
        if (requestedPly < moves[0].ply || requestedPly > moves[moves.length - 1].ply) {
          selectedIndex = requestedPly < moves[0].ply ? 0 : moves.length - 1
          // Resolve an out-of-range link once. A paused board must not drift
          // toward a future requested ply as the live match grows.
          clampedPly = moves[selectedIndex].ply
        } else error = `Ply ${route.ply} is not stored for this match. Choose another position or the latest move.`
      }
      if (clampedPly != null) status = `Ply ${route.ply} was outside the available range. Showing stored ply ${clampedPly}.`
    } else if (!error && route.ply != null && game && !loading) {
      error = `Ply ${route.ply} is not stored for this match. No moves are available yet.`
    }
    if (error) {
      game = null
      moves = []
      selectedIndex = null
    }
    state.set({
      game, moves, displayedMove: error ? null : moves[following ? moves.length - 1 : selectedIndex] || null,
      selectedIndex, following, explicitMatch, archived: explicitMatch && !live,
      loading: loading && !game, error, canRetry: !!requestError && !route.error && !live, status,
    })
  }

  async function load() {
    const token = ++generation
    controller?.abort()
    controller = null
    loading = false
    requestError = ''
    const id = route.matchId
    if (route.view !== 'showcase' || id == null || route.error || destroyed) { publish(); return }
    // The WebSocket installs the complete current-game move history. Local
    // scrubbing can use it without downloading the same boards and heatmaps.
    if (matchingLive() && movesForLiveGame().length) { publish(); return }
    loading = true
    controller = new AbortController()
    publish()
    try {
      const response = await fetchGame(`/api/showcase/games/${id}`, { signal: controller.signal })
      if (token !== generation || destroyed) return
      if (!response.ok) {
        throw new Error(response.status === 404 ? `Match ${id} is unavailable. Choose another match or watch the latest match.` : `Could not load match ${id} (${response.status}). Retry or watch the latest match.`)
      }
      const data = await response.json()
      if (token !== generation || destroyed) return
      if (!data.game || Number(data.game.id) !== id) throw new Error('The server returned a different match. Retry or watch the latest match.')
      const moves = orderedMoves(data.moves, id)
      // Matching live data is newer than an in-flight archive snapshot.
      cached = matchingLive() ? { game: liveGame, moves: orderedMoves([...new Map([...moves, ...movesForLiveGame()].map(move => [move.ply, move])).values()], id) } : { game: data.game, moves }
    } catch (cause) {
      if (token !== generation || destroyed) return
      if (cause.name !== 'AbortError') requestError = cause.message || 'Could not load this match. Retry or watch the latest match.'
    } finally {
      if (token === generation && !destroyed) {
        loading = false
        controller = null
        publish()
      }
    }
  }

  const unsubscribers = [
    navigationStore.subscribe(next => {
      const identityChanged = next.matchId !== route.matchId || next.view !== route.view || next.error !== route.error
      const previousId = route.matchId
      if (next.matchId !== route.matchId || next.ply !== route.ply || next.view !== route.view) clampedPly = null
      route = next
      if (previousId !== route.matchId) cached = null
      captureLive()
      if (identityChanged) load()
      else publish()
    }),
    liveGameStore.subscribe(next => {
      const previous = liveGame
      liveGame = next
      captureLive()
      // The final state of an explicitly viewed match can arrive just as the
      // latest feed advances; refresh its retained identity rather than follow.
      if (route.matchId != null && Number(previous?.id) === route.matchId && !matchingLive()) load()
      else publish()
    }),
    liveMovesStore.subscribe(next => { liveMoves = next; captureLive(); publish() }),
  ]

  return {
    subscribe: state.subscribe,
    retry: load,
    destroy() {
      destroyed = true
      generation++
      controller?.abort()
      unsubscribers.forEach(unsubscribe => unsubscribe())
    },
  }
}
