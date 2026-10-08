// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { tick } from 'svelte'
import MatchQueue from './MatchQueue.svelte'
import { showcaseQueue } from '../stores/showcase.js'
import { showcaseCommandPending, connectionState } from './ws.js'

let component
afterEach(() => { component?.$destroy(); showcaseCommandPending.set(null); document.body.innerHTML = '' })

it('prevents another cancellation while a command is awaiting confirmation', async () => {
  connectionState.set('connected')
  showcaseQueue.set([{ id: 1, status: 'pending', entry_id_1: '1', entry_id_2: '2', speed: 'normal' }])
  component = new MatchQueue({ target: document.body })
  showcaseCommandPending.set({ request_id: 'pending' })
  await tick()
  expect(document.querySelector('button').disabled).toBe(true)
  showcaseCommandPending.set(null)
  await tick()
  expect(document.querySelector('button').disabled).toBe(false)
})
