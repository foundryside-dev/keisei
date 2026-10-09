import { describe, expect, it } from 'vitest'
import { evaluationHistory, validateEvaluation } from './showcaseEvaluation.js'
const move = (score = 0.8, player = 'black', overrides = {}) => ({
  ply: 4, current_player: player === 'black' ? 'white' : 'black', value_estimate: 0.99,
  evaluation_json: { version: 1, kind: 'outcome_score', score, player, position_ply: 3,
    source: { architecture: 'resnet', contract: 'scalar' }, ...overrides },
})
describe('qualified Showcase evaluation', () => {
  it('orients player scores once regardless of post-move current player', () => {
    expect(validateEvaluation(move()).blackScore).toBeCloseTo(0.8)
    expect(validateEvaluation(move(0.8, 'white')).blackScore).toBeCloseTo(0.2)
    expect(validateEvaluation({ ...move(), current_player: 'black' }).blackScore).toBeCloseTo(0.8)
    expect(validateEvaluation(move()).label).toBe('Black outcome estimate before move 4')
  })
  it('supports WDL draw credit and opposite perspective', () => {
    const wdl = { win: 0.2, draw: 0.7, loss: 0.1 }
    expect(validateEvaluation(move(0.55, 'black', { wdl })).blackScore).toBeCloseTo(0.55)
    expect(validateEvaluation(move(0.55, 'white', { wdl })).blackScore).toBeCloseTo(0.45)
    expect(validateEvaluation(move(0.5, 'white', { wdl: { win: 0, draw: 1, loss: 0 } })).blackScore).toBe(0.5)
  })
  it.each([null, '{bad', {}, { version: 2 },
    ...[NaN, Infinity, -0.1, 1.1, '0.8'].map(score => move(score).evaluation_json),
    move(0.8, 'unknown').evaluation_json, move(0.8, 'black', { position_ply: 4 }).evaluation_json,
    move(0.8, 'black', { source: null }).evaluation_json,
    move(0.8, 'black', { wdl: { win: 0.2, draw: 0.7, loss: 0.1 } }).evaluation_json,
  ])('rejects invalid or legacy evaluation without a neutral fallback: %s', evaluation_json => {
    const result = validateEvaluation({ ply: 4, value_estimate: 0.5, evaluation_json })
    expect(result.available).toBe(false)
    expect(result.blackScore).toBeNull()
    expect(result.reason).toBeTruthy()
  })
  it('reads persisted JSON and preserves graph gaps tied to stored moves', () => {
    const good = move()
    good.evaluation_json = JSON.stringify(good.evaluation_json)
    expect(evaluationHistory([good, { ply: 5, value_estimate: 0.4 }])).toMatchObject([
      { index: 0, positionPly: 3, value: 0.8 }, { index: 1, positionPly: 4, value: null },
    ])
  })
})
