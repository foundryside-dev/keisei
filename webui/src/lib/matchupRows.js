/** Full identities remain distinguishable when snapshots share a display name. */
export function matchupIdentity(entry) {
  if (entry.isTrainer) return entry.label
  return `${entry.display_name || entry.architecture || entry.label || 'Unknown'} · #${entry.id} · epoch ${entry.created_epoch ?? 'unknown'}`
}

/** Emit unordered pairs once, or orient every result to the selected player. */
export function matchupRows(participants, recordFor, selectedId = '') {
  const players = participants.filter(p => !p.isPlaceholder)
  const rows = []
  if (selectedId !== '') {
    const player = players.find(p => String(p.id) === String(selectedId))
    if (!player) return rows
    for (const opponent of players) {
      if (player.id === opponent.id) continue
      const record = recordFor(player.id, opponent.id)
      if (record?.total > 0) rows.push({ player, opponent, ...record })
    }
    return rows
  }
  for (let i = 0; i < players.length; i++) {
    for (let j = i + 1; j < players.length; j++) {
      const record = recordFor(players[i].id, players[j].id)
      if (record?.total > 0) rows.push({ player: players[i], opponent: players[j], ...record })
    }
  }
  return rows
}
