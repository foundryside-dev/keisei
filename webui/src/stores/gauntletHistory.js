import { writable } from 'svelte/store'

/** Paged results are independent of the WebSocket's bounded latest-50 window. */
export function createGauntletHistory(fetchPage = (url, options) => fetch(url, options)) {
  const state = writable({ epochs: [], loading: false, error: '', hasMore: true })
  let records = new Map()
  let visibleEpochs = new Set()
  let newestEpoch = null
  let generation = 0
  let request = null
  let loading = false
  let error = ''
  let hasMore = true
  let context

  function publish() {
    const grouped = new Map([...visibleEpochs].map(epoch => [epoch, []]))
    for (const row of records.values()) grouped.get(row.epoch)?.push(row)
    const epochs = [...grouped].filter(([, rows]) => rows.length).sort((a, b) => b[0] - a[0])
    state.set({ epochs, loading, error, hasMore })
  }

  function setContext(next) {
    if (next === context) return
    context = next
    generation++
    request?.abort()
    request = null
    records = new Map()
    visibleEpochs = new Set()
    newestEpoch = null
    loading = false
    error = ''
    hasMore = true
    publish()
  }

  function merge(rows) {
    for (const row of rows) {
      // The API and live feed expose persisted IDs; never deduplicate by epoch/slot.
      if (row.id != null) records.set(row.id, row)
    }
  }

  function setLive(rows) {
    merge(rows)
    const epochs = [...new Set(rows.map(row => row.epoch))].sort((a, b) => b - a)
    if (newestEpoch == null) {
      epochs.slice(0, 5).forEach(epoch => visibleEpochs.add(epoch))
    } else {
      epochs.filter(epoch => epoch > newestEpoch).forEach(epoch => visibleEpochs.add(epoch))
    }
    if (epochs.length) newestEpoch = Math.max(newestEpoch ?? -Infinity, epochs[0])
    publish()
  }

  async function loadOlder() {
    if (loading || !hasMore) return
    const token = generation
    const before = visibleEpochs.size ? Math.min(...visibleEpochs) : null
    const query = new URLSearchParams({ limit: '5' })
    if (before != null) query.set('before_epoch', String(before))
    loading = true
    error = ''
    request = new AbortController()
    publish()
    try {
      const response = await fetchPage(`/api/league/gauntlet?${query}`, { signal: request.signal })
      if (!response.ok) throw new Error(`History request failed (${response.status})`)
      const page = await response.json()
      if (token !== generation) return
      if (!Array.isArray(page.results) || typeof page.has_more !== 'boolean') throw new Error('Invalid history response')
      merge(page.results)
      page.results.forEach(row => visibleEpochs.add(row.epoch))
      hasMore = page.has_more
      if (page.results.length) newestEpoch = Math.max(newestEpoch ?? -Infinity, ...page.results.map(row => row.epoch))
    } catch (cause) {
      if (token !== generation) return
      if (cause.name !== 'AbortError') error = 'Could not load older evaluations. Your loaded results are still available.'
    } finally {
      if (token === generation) {
        loading = false
        request = null
        publish()
      }
    }
  }

  return { subscribe: state.subscribe, setContext, setLive, loadOlder }
}

export const gauntletHistory = createGauntletHistory()
