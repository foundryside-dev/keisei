async (page) => {
  // Preparation: on the disposable fixture only, focus .list-toggle while
  // unfiltered records exist, then empty head_to_head and league_results in one
  // transaction. The real league WebSocket update disables the disclosure.
  await page.locator('.list-toggle:disabled').waitFor()
  const result = await page.locator('.player-filter select').evaluate(node => ({ focusedFilter: node === document.activeElement, activeTag: document.activeElement.tagName }))
  if (!result.focusedFilter) throw new Error('Disabling a focused disclosure lost the useful focus target')
  return { ...result, recordsEmpty: await page.locator('#matchup-records').innerText() }
}
