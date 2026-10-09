import { writable, derived, get } from 'svelte/store'
import { leagueEntries } from './league.js'

const gameRows = writable([])
const selectedId = writable(null)
export const laneAnnouncement = writable({ message: '', revision: 0 })
function announceLane(message) {
  laneAnnouncement.update(previous => ({ message, revision: previous.revision + 1 }))
}
function reconcile(rows, requested, previous = []) {
  let selected = rows.find(g => g.game_id === requested)
  if (!selected) {
    selected = [...rows].sort((a, b) => Number(!!a.is_over) - Number(!!b.is_over) || a.game_id - b.game_id)[0]
    if (requested != null) announceLane(selected ? `Lane ${requested + 1} is unavailable. Selected lane ${selected.game_id + 1}.` : 'No training lanes available.')
  } else {
    const old = previous.find(g => g.game_id === requested)
    if (old && ((old.is_over && !selected.is_over) || selected.ply < old.ply)) announceLane(`New game in lane ${requested + 1}`)
  }
  selectedId.set(selected?.game_id ?? null)
}
export const games = {
  subscribe: gameRows.subscribe,
  set(rows) { const old = get(gameRows); gameRows.set(rows); reconcile(rows, get(selectedId), old) },
  update(fn) { this.set(fn(get(gameRows))) },
}
export const selectedGameId = {
  subscribe: selectedId.subscribe,
  set(id) { reconcile(get(gameRows), id) },
  update(fn) { this.set(fn(get(selectedId))) },
}
export const selectedGame = derived(
  [games, selectedGameId],
  ([$games, $id]) => $games.find(g => g.game_id === $id) || null
)

export const selectedOpponent = derived(
  [selectedGame, leagueEntries],
  ([$game, $entries]) => {
    if (!$game?.opponent_id) return null
    const entry = $entries.find(e => e.id === $game.opponent_id)
    if (!entry) return null
    return {
      display_name: entry.display_name || entry.architecture,
      architecture: entry.architecture,
      elo_rating: entry.elo_rating,
      games_played: entry.games_played,
      created_epoch: entry.created_epoch,
      flavour_facts: entry.flavour_facts || [],
      model_params: entry.model_params || {},
      created_at: entry.created_at || '',
    }
  }
)
