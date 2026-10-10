async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Replay · ply 12$/ }).waitFor()
  check(new URL(page.url()).searchParams.get('match') === '4', 'Back-selected explicit match followed the next match')
  await page.getByRole('button', { name: 'Watch latest match', exact: true }).click()
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  await page.getByRole('button', { name: 'Pause following', exact: true }).click()
  check(new URL(page.url()).searchParams.get('match') === '5', 'Latest feed did not show match 5')
  return { explicitIdentityAfterRollover: 4, pausedLatestBeforeNextRollover: page.url() }
}
