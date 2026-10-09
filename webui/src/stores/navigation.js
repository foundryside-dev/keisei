import { writable } from 'svelte/store'

const VIEWS = new Set(['training', 'league', 'showcase', 'about'])
const OWNED_PARAMS = ['view', 'entry', 'match', 'ply']

function integer(value, minimum) {
  if (value == null || !/^\d+$/.test(String(value))) return null
  const number = Number(value)
  return Number.isSafeInteger(number) && number >= minimum ? number : null
}

/** URL syntax only; existence and stored-ply validation belong to data adapters. */
export function parseNavigation(url, savedView = 'training') {
  const params = url.searchParams
  const explicit = OWNED_PARAMS.some(key => params.has(key))
  const fallback = VIEWS.has(savedView) ? savedView : 'training'
  const view = explicit ? params.get('view') : fallback
  const result = { view: VIEWS.has(view) ? view : 'training', entryId: null, matchId: null, ply: null, error: '' }
  if (explicit && !VIEWS.has(view)) result.error = 'This link has an invalid dashboard view. Choose a view to continue.'
  for (const [key, property, minimum, expectedView] of [
    ['entry', 'entryId', 1, 'league'], ['match', 'matchId', 1, 'showcase'], ['ply', 'ply', 0, 'showcase'],
  ]) {
    if (!params.has(key)) continue
    const value = integer(params.get(key), minimum)
    if (result.view !== expectedView || value == null) {
      result.error = `This link has an invalid ${key}. Choose another ${key === 'entry' ? 'entry' : 'match'} to continue.`
    } else result[property] = value
  }
  if (result.ply != null && result.matchId == null) result.error = 'A saved position needs a match. Choose a match to continue.'
  return result
}

/** User navigation writes history; popstate only reads it. */
export function createNavigation(browser = typeof window === 'undefined' ? null : window, storage = undefined) {
  if (storage === undefined) {
    try { storage = browser?.localStorage } catch { storage = null }
  }
  function savedView() {
    try { return storage?.getItem('activeTab') } catch { return null }
  }
  const currentUrl = () => new URL(browser?.location.href || 'http://localhost/')
  let current = parseNavigation(currentUrl(), savedView())
  const state = writable(current)

  function publish(next) {
    current = next
    state.set(next)
    try { storage?.setItem('activeTab', next.view) } catch { /* Storage is optional. */ }
  }
  publish(current)

  function destinationUrl(next) {
    const url = currentUrl()
    OWNED_PARAMS.forEach(key => url.searchParams.delete(key))
    url.searchParams.set('view', next.view)
    if (next.view === 'league' && next.entryId != null) url.searchParams.set('entry', String(next.entryId))
    if (next.view === 'showcase' && next.matchId != null) {
      url.searchParams.set('match', String(next.matchId))
      if (next.ply != null) url.searchParams.set('ply', String(next.ply))
    }
    return url
  }

  function write(next, replace = false) {
    const url = destinationUrl(next)
    if (browser && url.href !== browser.location.href) {
      browser.history[replace ? 'replaceState' : 'pushState'](browser.history.state, '', url)
    }
    publish(next)
  }

  function selectView(view) {
    if (!VIEWS.has(view)) return
    write({ view, entryId: null, matchId: null, ply: null, error: '' })
  }
  function selectEntry(id) {
    const entryId = id == null ? null : integer(id, 1)
    if (id != null && entryId == null) throw new TypeError('Entry ID must be a positive integer')
    write({ view: 'league', entryId, matchId: null, ply: null, error: '' })
  }
  function selectMatch(id, ply = null, { replace = false } = {}) {
    const matchId = id == null ? null : integer(id, 1)
    const position = ply == null ? null : integer(ply, 0)
    if (id != null && matchId == null) throw new TypeError('Match ID must be a positive integer')
    if (ply != null && (position == null || matchId == null)) throw new TypeError('A ply needs a match and a nonnegative integer')
    write({ view: 'showcase', entryId: null, matchId, ply: position, error: '' }, replace)
  }
  function setReplayPly(ply, matchId = current.matchId) {
    selectMatch(matchId, ply, { replace: true })
  }
  function readHistory() { publish(parseNavigation(currentUrl(), savedView())) }
  browser?.addEventListener('popstate', readHistory)

  const activeTab = {
    subscribe: callback => state.subscribe(value => callback(value.view)),
    set: selectView,
    update: callback => selectView(callback(current.view)),
  }
  return {
    subscribe: state.subscribe, activeTab, selectView, selectEntry, selectMatch, setReplayPly,
    watchLatestMatch: () => selectMatch(null),
    async copyCurrentLink(clipboard = browser?.navigator.clipboard) {
      try {
        if (!clipboard?.writeText) throw new Error('Clipboard unavailable')
        await clipboard.writeText(destinationUrl(current).href)
        return { ok: true, message: 'Link copied.' }
      } catch { return { ok: false, message: 'Could not copy the link. Copy the address from your browser.' } }
    },
    destroy: () => browser?.removeEventListener('popstate', readHistory),
  }
}

export const navigation = createNavigation()
export const activeTab = navigation.activeTab
export const selectEntry = navigation.selectEntry
export const selectMatch = navigation.selectMatch
export const setReplayPly = navigation.setReplayPly
export const watchLatestMatch = navigation.watchLatestMatch
export const copyCurrentLink = navigation.copyCurrentLink
