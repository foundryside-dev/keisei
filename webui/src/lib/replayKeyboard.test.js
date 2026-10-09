// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { replayAction } from './replayKeyboard.js'
it('leaves native controls, move log scrolling and cancelled/modifier keys alone', () => {
  for (const html of ['<button>Heatmap</button>', '<input>', '<details><summary>Position as text</summary></details>', '<div role="tab"></div>', '<div role="log"><span></span></div>', '<div contenteditable="true"></div>']) {
    const div = document.createElement('div'); div.innerHTML = html
    expect(replayAction({ key: ' ', target: div.querySelector('summary,span') || div.firstChild })).toBeNull()
  }
  expect(replayAction({ key: 'h', defaultPrevented: true })).toBeNull()
  expect(replayAction({ key: 'Home', ctrlKey: true })).toBeNull()
  expect(replayAction({ key: 'ArrowLeft', shiftKey: true })).toEqual({ step: -5 })
  expect(replayAction({ key: ' ' })).toBe('pause')
})
