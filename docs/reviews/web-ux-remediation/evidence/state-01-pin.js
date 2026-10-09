async (page) => {
  await page.goto('http://127.0.0.1:8765/?view=showcase&match=3')
  await page.getByRole('region', { name: 'Replay keyboard controls', exact: true }).waitFor()
  const cell = page.getByRole('button', { name: 'P*1b', exact: true })
  const historyBefore = await page.evaluate(() => {
    window.__replayReplacements = 0
    const original = history.replaceState.bind(history)
    history.replaceState = (...args) => { window.__replayReplacements++; return original(...args) }
    return history.length
  })
  await cell.focus()
  await page.keyboard.press('Space')
  await page.waitForURL(/ply=1(?:&|$)/)
  if (await cell.getAttribute('aria-pressed') !== 'true') throw new Error('Space did not pin selected move')
  const historyAfter = await page.evaluate(() => history.length)
  const replacements = await page.evaluate(() => window.__replayReplacements)
  if (historyAfter !== historyBefore || replacements !== 1) throw new Error(`Move Space replacement count ${replacements}; history delta ${historyAfter-historyBefore}`)
  const moveSpace = { url: page.url(), historyEntriesAdded: historyAfter - historyBefore, replacementCalls: replacements, pressed: await cell.getAttribute('aria-pressed') }
  await page.getByRole('button', { name: 'Resume following', exact: true }).click()
  await page.getByRole('button', { name: 'Pause following', exact: true }).click()
  const paused = await page.locator('.viewer-toolbar strong').textContent()
  if (!paused.includes('Paused at ply 13')) throw new Error(`Tail was not immediately pinned: ${paused}`)
  return { moveSpace, tailPinned: { url: page.url(), label: paused } }
}
