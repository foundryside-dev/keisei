import { HAND_PIECE_ORDER } from './pieces.js'

export function describePosition(board = [], hands = {}, currentPlayer = 'black', includeEmpty = false) {
  const squares = Array.from({ length: 81 }, (_, index) => {
    const piece = board[index]
    return { coordinate: `${9 - index % 9}${'abcdefghi'[Math.floor(index / 9)]}`, side: piece?.color || '', piece: piece ? `${piece.promoted ? 'Promoted ' : ''}${piece.type}` : 'Empty', promoted: !!piece?.promoted }
  }).filter(square => includeEmpty || square.side)
  const held = ['black', 'white'].map(side => ({ side, pieces: HAND_PIECE_ORDER.filter(type => Number(hands[side]?.[type]) > 0).map(type => `${type} × ${hands[side][type]}`).join(', ') || 'None' }))
  return { squares, held, currentPlayer }
}
