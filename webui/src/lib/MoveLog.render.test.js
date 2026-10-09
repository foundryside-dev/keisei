// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import MoveLog from './MoveLog.svelte'

// Use browser lifecycle hooks; Vitest's Node export conditions otherwise
// resolve the public Svelte module to its SSR no-op lifecycle functions.
vi.mock('svelte', async () => import('svelte/internal'))

let component
const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
const history = count => JSON.stringify(['7g7f','3c3d','2g2f','8c8d'].slice(0,count).map(notation => ({ notation })))
const settle = async () => { await tick(); await tick() }
afterEach(() => {
  component?.$destroy(); document.body.innerHTML = ''; vi.restoreAllMocks()
  if (originalScrollIntoView) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView)
  else delete Element.prototype.scrollIntoView
})

it('appends following moves without scrolling ancestors or disturbing reviewed history', async () => {
  const scrollIntoView = vi.fn()
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  component = new MoveLog({ target: document.body, props: { moveHistoryJson: history(3), interactive: true, selectedIdx: 2, following: true } })
  await settle()
  const region = document.querySelector('[data-move-log]')
  region.scrollTop = 75
  component.$set({ moveHistoryJson: history(4), selectedIdx: 3 }); await settle()
  expect(region.scrollTop).toBe(75)
  expect(scrollIntoView).not.toHaveBeenCalled()
  expect(document.documentElement.scrollTop).toBe(0)
})

it('scrolls only the local move container after an explicit pinned selection', async () => {
  const scrollIntoView = vi.fn()
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  component = new MoveLog({ target: document.body, props: { moveHistoryJson: history(4), interactive: true, selectedIdx: 3, following: true } })
  await settle()
  const region = document.querySelector('[data-move-log]')
  region.scrollTop = 30
  vi.spyOn(region, 'getBoundingClientRect').mockReturnValue({ top: 100, bottom: 200 })
  document.querySelectorAll('td[role="button"]').forEach(cell => vi.spyOn(cell, 'getBoundingClientRect').mockReturnValue({ top: 250, bottom: 280 }))
  component.$set({ selectedIdx: 0, following: false }); await settle()
  expect(region.scrollTop).toBe(110)
  expect(scrollIntoView).not.toHaveBeenCalled()
  expect(document.documentElement.scrollTop).toBe(0)
  component.$set({ moveHistoryJson: history(3) }); await settle()
  expect(region.scrollTop).toBe(110)
})
