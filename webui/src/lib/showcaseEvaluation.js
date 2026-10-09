/** Validate explicit pre-move evaluation metadata. Legacy scalar values are not interchangeable. */
export function validateEvaluation(move) {
  const unavailable = reason => ({ available: false, blackScore: null, label: 'Estimate unavailable', reason })
  const raw = move?.evaluation_json ?? move?.evaluation
  if (raw == null) return unavailable('No qualified evaluation was stored for this position.')
  let value
  try { value = typeof raw === 'string' ? JSON.parse(raw) : raw }
  catch { return unavailable('Stored evaluation could not be read.') }
  if (!value || value.version !== 1 || value.kind !== 'outcome_score') {
    return unavailable('Unsupported evaluation format.')
  }
  if (typeof value.score !== 'number' || !Number.isFinite(value.score) || value.score < 0 || value.score > 1) {
    return unavailable('Stored outcome score is invalid.')
  }
  if (!['black', 'white'].includes(value.player)) return unavailable('Evaluated player is unknown.')
  if (!Number.isSafeInteger(value.position_ply) || value.position_ply < 0 ||
      !Number.isSafeInteger(move?.ply) || value.position_ply !== move.ply - 1) {
    return unavailable('Evaluated position does not match this move.')
  }
  if (typeof value.source?.architecture !== 'string' || !value.source.architecture.trim() ||
      !['scalar', 'multi_head'].includes(value.source?.contract)) {
    return unavailable('Evaluation model source is unknown.')
  }
  if (value.wdl != null) {
    const probs = ['win', 'draw', 'loss'].map(key => value.wdl[key])
    if (probs.some(p => typeof p !== 'number' || !Number.isFinite(p) || p < 0 || p > 1) ||
        Math.abs(probs.reduce((a, b) => a + b, 0) - 1) > 1e-5 ||
        Math.abs(probs[0] + 0.5 * probs[1] - value.score) > 1e-5) {
      return unavailable('Stored W/D/L probabilities are invalid.')
    }
  }
  return {
    available: true,
    blackScore: value.player === 'black' ? value.score : 1 - value.score,
    score: value.score, player: value.player, positionPly: value.position_ply,
    movePly: move.ply, source: value.source,
    label: `Black outcome estimate before move ${move.ply}`, reason: null,
  }
}

/** Preserve invalid points as gaps; each plotted point selects its associated stored move. */
export function evaluationHistory(moves) {
  return (moves ?? []).map((move, index) => {
    const evaluation = validateEvaluation(move)
    return {
      index, move, evaluation,
      positionPly: evaluation.available ? evaluation.positionPly : move.ply - 1,
      value: evaluation.blackScore,
    }
  })
}
