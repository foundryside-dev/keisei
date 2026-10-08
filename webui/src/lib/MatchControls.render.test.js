// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { tick } from 'svelte'
import { get } from 'svelte/store'
import MatchControls from './MatchControls.svelte'
import { showcaseGame, showcaseQueue, showcaseSpeed, sidecarAlive } from '../stores/showcase.js'
import { connect, disconnect, handleMessage } from './ws.js'

let component, socket
beforeEach(() => {
  vi.stubGlobal('WebSocket', class {
    static OPEN = 1
    constructor() { this.readyState = 1; this.send = vi.fn(); socket = this }
    close() {}
  })
  connect()
  socket.onopen()
  sidecarAlive.set(true)
  showcaseGame.set({ id: 9, queue_id: 42 })
  showcaseQueue.set([{ id: 42, status: 'running', speed: 'normal' }])
  showcaseSpeed.set('slow')
  component = new MatchControls({ target: document.body, props: { collapsed: true } })
})
afterEach(() => { component.$destroy(); disconnect(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
const speedButton = (speed) => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === speed)

it('targets the running queue and shows only confirmed playback speed', async () => {
  expect(speedButton('normal').getAttribute('aria-pressed')).toBe('true')
  speedButton('fast').click()
  await tick()
  const command = JSON.parse(socket.send.mock.calls[0][0])
  expect(command).toMatchObject({ type: 'change_showcase_speed', queue_id: 42, speed: 'fast', request_id: expect.any(String) })
  expect(speedButton('normal').getAttribute('aria-pressed')).toBe('true')
  expect(get(showcaseSpeed)).toBe('slow')
  handleMessage({ type: 'showcase_speed_changed', queue_id: 42, speed: 'fast', request_id: command.request_id })
  await tick()
  expect(speedButton('fast').getAttribute('aria-pressed')).toBe('true')
})

it('renders server rejection and retains the confirmed speed', async () => {
  speedButton('fast').click()
  await tick()
  const command = JSON.parse(socket.send.mock.calls[0][0])
  handleMessage({ type: 'showcase_error', error: 'Match is no longer running', request_id: command.request_id })
  await tick()
  expect(document.querySelector('[role="alert"]')?.textContent).toContain('Match is no longer running')
  expect(speedButton('normal').getAttribute('aria-pressed')).toBe('true')
})

it('changes future-match preference locally when no game is running', async () => {
  showcaseGame.set(null)
  showcaseQueue.set([])
  component.$set({ collapsed: false })
  await tick()
  speedButton('fast').click()
  await tick()
  expect(get(showcaseSpeed)).toBe('fast')
  expect(socket.send).not.toHaveBeenCalled()
})
