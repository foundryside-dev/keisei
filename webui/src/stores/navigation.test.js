// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { get } from 'svelte/store'
import { createNavigation, navigation, parseNavigation } from './navigation.js'

navigation.destroy()
let nav
beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/') })
afterEach(() => { nav?.destroy(); vi.restoreAllMocks() })
function create() { nav = createNavigation(window); return nav }

describe('dashboard query navigation', () => {
  it('validates saved views and gives explicit URLs precedence', () => {
    localStorage.setItem('activeTab', 'league')
    expect(get(create()).view).toBe('league')
    nav.destroy()
    localStorage.setItem('activeTab', 'games')
    expect(get(create()).view).toBe('training')
    nav.destroy()
    localStorage.setItem('activeTab', 'league')
    history.replaceState(null, '', '/?view=showcase&match=123&ply=17')
    expect(get(create())).toEqual({ view: 'showcase', entryId: null, matchId: 123, ply: 17, error: '' })
    expect(localStorage.getItem('activeTab')).toBe('showcase')
  })
  it.each(['-1', '1.5', 'NaN', '', '9007199254740992', 'oops'])('rejects malformed match IDs: %s', id => {
    expect(parseNavigation(new URL(`http://localhost/?view=showcase&match=${id}`))).toMatchObject({ matchId: null, error: expect.stringMatching(/invalid match/) })
  })
  it('reports invalid views, orphan plies and invalid entries', () => {
    expect(parseNavigation(new URL('http://localhost/?view=games'), 'league')).toMatchObject({ view: 'training', error: expect.stringMatching(/invalid dashboard/) })
    expect(parseNavigation(new URL('http://localhost/?view=showcase&ply=2')).error).toMatch(/needs a match/)
    expect(parseNavigation(new URL('http://localhost/?view=league&entry=0'))).toMatchObject({ entryId: null, error: expect.stringMatching(/invalid entry/) })
  })
  it('pushes destinations and replaces scrubs while preserving unrelated query/hash', () => {
    history.replaceState(null, '', '/?experiment=abc#about-big-idea')
    create()
    const push = vi.spyOn(history, 'pushState')
    const replace = vi.spyOn(history, 'replaceState')
    nav.selectEntry(42)
    nav.selectMatch(123, 17)
    nav.setReplayPly(18)
    nav.setReplayPly(null)
    expect(push).toHaveBeenCalledTimes(2)
    expect(replace).toHaveBeenCalledTimes(2)
    expect(location.search).toBe('?experiment=abc&view=showcase&match=123')
    expect(location.hash).toBe('#about-big-idea')
    nav.activeTab.set('about')
    expect(location.search).toBe('?experiment=abc&view=about')
    expect(get(nav).matchId).toBeNull()
  })
  it('pins a live match when scrubbing begins and explicitly returns to latest', () => {
    create().setReplayPly(17, 123)
    expect(get(nav)).toMatchObject({ matchId: 123, ply: 17 })
    nav.watchLatestMatch()
    expect(get(nav)).toMatchObject({ matchId: null, ply: null })
  })
  it('reads browser Back/Forward without history write loops', async () => {
    create().selectEntry(42)
    nav.selectMatch(123, 17)
    const push = vi.spyOn(history, 'pushState')
    const replace = vi.spyOn(history, 'replaceState')
    const back = new Promise(resolve => window.addEventListener('popstate', resolve, { once: true }))
    history.back()
    await back
    expect(get(nav)).toMatchObject({ view: 'league', entryId: 42, matchId: null })
    const forward = new Promise(resolve => window.addEventListener('popstate', resolve, { once: true }))
    history.forward()
    await forward
    expect(get(nav)).toMatchObject({ view: 'showcase', matchId: 123, ply: 17 })
    expect(push).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
  })
  it('keeps a compatible activeTab store without persisting unsupported values', () => {
    create().activeTab.set('league')
    nav.activeTab.update(() => 'training')
    nav.activeTab.set('games')
    expect(get(nav.activeTab)).toBe('training')
    expect(localStorage.getItem('activeTab')).toBe('training')
  })
  it('reports clipboard success and failure', async () => {
    create().selectMatch(123, 17)
    const writeText = vi.fn().mockResolvedValue(undefined)
    expect(await nav.copyCurrentLink({ writeText })).toMatchObject({ ok: true })
    expect(writeText).toHaveBeenCalledWith(location.href)
    expect(await nav.copyCurrentLink({ writeText: vi.fn().mockRejectedValue(new Error('Denied')) })).toMatchObject({ ok: false })
  })
  it('copies the resolved saved view even before the first navigation action', async () => {
    localStorage.setItem('activeTab', 'league')
    const writeText = vi.fn().mockResolvedValue(undefined)
    await create().copyCurrentLink({ writeText })
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/?view=league`)
    expect(location.search).toBe('')
  })
  it('works without browser storage', () => {
    nav = createNavigation(window, { getItem() { throw new Error('Denied') }, setItem() { throw new Error('Denied') } })
    nav.selectEntry(42)
    expect(get(nav).entryId).toBe(42)
  })
})
