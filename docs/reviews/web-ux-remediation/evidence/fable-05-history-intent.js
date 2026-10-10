async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('http://127.0.0.1:8768/?view=showcase&match=4&ply=2')
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Paused at ply 2$/ }).waitFor()
  await page.getByRole('button', { name: 'Watch latest match', exact: true }).click()
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  await page.getByRole('button', { name: 'Pause following', exact: true }).click()
  await page.goBack()
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Paused at ply 2$/ }).waitFor()
  await page.getByRole('button', { name: 'Resume following', exact: true }).click()
  check(new URL(page.url()).searchParams.get('match') === '4' && !new URL(page.url()).searchParams.has('ply'), 'Same-ID Back retained latest-feed intent')
  return { afterSameMatchBackAndResume: page.url(), state: await page.locator('.viewer-toolbar strong').innerText() }
}
