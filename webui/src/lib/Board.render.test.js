// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from 'vitest'
import { tick } from 'svelte'
import Board from './Board.svelte'
import BoardPosition from './BoardPosition.svelte'

let boardComponent, positionComponent
const fixture = () => {
  const board = Array(81).fill(null)
  board[4] = { type: 'king', color: 'white', promoted: false }
  board[76] = { type: 'king', color: 'black', promoted: false }
  board[40] = { type: 'pawn', color: 'black', promoted: true }
  return { board, hands: { black: { rook: 2 }, white: { pawn: 3 } }, currentPlayer: 'white' }
}
const rows = () => [...document.querySelectorAll('.position-text tbody tr')].map(row => [...row.children].map(cell => cell.textContent))
beforeEach(() => {
  const props = fixture()
  boardComponent = new Board({ target: document.body, props: { board: props.board, currentPlayer: props.currentPlayer, inCheck: true } })
  positionComponent = new BoardPosition({ target: document.body, props })
})
afterEach(() => { boardComponent.$destroy(); positionComponent.$destroy(); document.body.innerHTML = '' })

it('renders the complete visual board and the same kings, promoted piece, hands and side in text', () => {
  expect(document.querySelectorAll('.board .square')).toHaveLength(81)
  expect(document.querySelectorAll('.col-labels span')).toHaveLength(9)
  expect(document.querySelectorAll('.row-labels span')).toHaveLength(9)
  expect(document.querySelectorAll('.board .has-piece')).toHaveLength(3)
  expect(document.querySelector('.board-container').getAttribute('aria-label')).toContain('white to move, in check')
  expect(document.querySelector('.board').getAttribute('aria-hidden')).toBe('true')
  expect(rows()).toEqual([
    ['5a', 'white', 'king'], ['5e', 'black', 'Promoted pawn'], ['5i', 'black', 'king'],
  ])
  const text = document.querySelector('.position-text').textContent
  expect(text).toContain('white to move')
  expect(text).toContain('black hand: rook × 2')
  expect(text).toContain('white hand: pawn × 3')
  expect(document.querySelector('.position-text caption').textContent).toBe('Displayed position')
  expect(document.querySelectorAll('.position-text tbody th[scope="row"]')).toHaveLength(3)
})

it('discloses occupied squares by default and all 81 squares only on request', async () => {
  const details = document.querySelector('.position-text')
  expect(details.open).toBe(false)
  expect(rows()).toHaveLength(3)
  details.open = true
  const includeEmpty = details.querySelector('input[type="checkbox"]')
  expect(includeEmpty.checked).toBe(false)
  includeEmpty.click()
  await tick()
  expect(rows()).toHaveLength(81)
  expect(rows().filter(row => row[2] === 'Empty')).toHaveLength(78)
  expect(rows()[0]).toEqual(['9a', '—', 'Empty'])
  includeEmpty.click()
  await tick()
  expect(rows()).toHaveLength(3)
})

it('updates both representations without making positions or squares live announcements', async () => {
  const next = fixture()
  next.board[49] = next.board[40]
  next.board[40] = null
  next.hands = { black: {}, white: { bishop: 1 } }
  next.currentPlayer = 'black'
  boardComponent.$set({ board: next.board, currentPlayer: next.currentPlayer, inCheck: false })
  positionComponent.$set(next)
  await tick()
  expect(document.querySelectorAll('.board .square')[49].querySelector('.promoted').textContent.trim()).toBe('と')
  expect(document.querySelectorAll('.board .square')[40].querySelector('.piece')).toBeNull()
  expect(rows()).toContainEqual(['5f', 'black', 'Promoted pawn'])
  expect(rows()).not.toContainEqual(['5e', 'black', 'Promoted pawn'])
  expect(document.querySelector('.position-text').textContent).toContain('black to move')
  expect(document.querySelector('.position-text').textContent).toContain('black hand: None')
  expect(document.querySelector('.position-text').textContent).toContain('white hand: bishop × 1')
  expect(document.querySelector('.board-container').getAttribute('aria-label')).toContain('black to move.')
  expect(document.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]')).toHaveLength(0)
})
