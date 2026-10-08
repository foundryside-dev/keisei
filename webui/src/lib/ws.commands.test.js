// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'
import { connect, disconnect, handleMessage, sendShowcaseCommand, showcaseCommandPending, showcaseCommandFeedback } from './ws.js'
import { showcaseQueue } from '../stores/showcase.js'

let socket
beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', class {
    static OPEN = 1
    constructor() { this.readyState = 1; this.send = vi.fn(); socket = this }
    close() {}
  })
  showcaseQueue.set([])
  connect()
})
afterEach(() => { disconnect(); vi.useRealTimers(); vi.unstubAllGlobals() })

it('does not send duplicate commands while awaiting confirmation', () => {
  expect(sendShowcaseCommand({ type: 'request_showcase_match' })).toBe(true)
  expect(sendShowcaseCommand({ type: 'request_showcase_match' })).toBe(false)
  expect(socket.send).toHaveBeenCalledTimes(1)
})

it('ignores an unrelated acknowledgement and releases the pending state on timeout', () => {
  sendShowcaseCommand({ type: 'request_showcase_match' })
  handleMessage({ type: 'showcase_match_queued', request_id: 'unrelated', queue_id: 123 })
  expect(get(showcaseCommandPending)).not.toBeNull()
  expect(get(showcaseQueue)).toEqual([])
  vi.advanceTimersByTime(10000)
  expect(get(showcaseCommandPending)).toBeNull()
  expect(get(showcaseCommandFeedback).message).toContain('Check the match queue')
})

it('shows loss of confirmation on disconnect and never retries the command', () => {
  sendShowcaseCommand({ type: 'request_showcase_match' })
  socket.onclose()
  expect(get(showcaseCommandPending)).toBeNull()
  expect(get(showcaseCommandFeedback).message).toContain('Connection lost before confirmation')
  expect(socket.send).toHaveBeenCalledTimes(1)
})

it('updates the queue from a correlated acknowledgement', () => {
  sendShowcaseCommand({ type: 'request_showcase_match', entry_id_1: '1', entry_id_2: '2', speed: 'slow' })
  const command = JSON.parse(socket.send.mock.calls[0][0])
  handleMessage({ ...command, type: 'showcase_match_queued', queue_id: 123 })
  expect(get(showcaseQueue)).toEqual([{ id: 123, entry_id_1: '1', entry_id_2: '2', speed: 'slow', status: 'pending' }])
  expect(get(showcaseCommandPending)).toBeNull()
})

it('reports offline commands without pretending they were sent', () => {
  disconnect()
  expect(sendShowcaseCommand({ type: 'request_showcase_match' })).toBe(false)
  expect(get(showcaseCommandFeedback).kind).toBe('error')
  expect(socket.send).not.toHaveBeenCalled()
})
