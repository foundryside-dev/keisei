import { expect, it } from 'vitest'
import { describePosition } from './boardPosition.js'

it('describes coordinates, promotion, hands and the displayed side without 81 empty rows', () => {
  const board = Array(81).fill(null)
  board[4] = { type: 'king', color: 'white', promoted: false }
  board[76] = { type: 'king', color: 'black', promoted: false }
  board[40] = { type: 'pawn', color: 'black', promoted: true }
  const result = describePosition(board, { black: { rook: 2 } }, 'white')
  expect(result.squares.map(s => [s.coordinate, s.piece])).toEqual([['5a', 'king'], ['5e', 'Promoted pawn'], ['5i', 'king']])
  expect(result.held[0].pieces).toBe('rook × 2')
  expect(result.currentPlayer).toBe('white')
  expect(describePosition(board, {}, 'black', true).squares).toHaveLength(81)
})
