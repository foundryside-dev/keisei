async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.waitForTimeout(700)
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.getByRole('button', { name: 'Copy link to this position', exact: true }).click()
  await page.getByText('Link copied.', { exact: true }).waitFor()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  check(new URL(copied).searchParams.get('match') === '4', 'Resumed latest feed stayed on old match')
  const rollover = { state: await page.locator('.viewer-toolbar strong').innerText(), copied, viewerUrl: page.url() }
  await page.goto('http://127.0.0.1:8768/?view=showcase&match=3&ply=12')
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Replay · ply 12$/ }).waitFor()
  await page.getByRole('button', { name: 'Resume following', exact: true }).click()
  check(new URL(page.url()).searchParams.get('match') === '3', 'Explicit saved-match resume lost identity')
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Replay · ply 13$/ }).waitFor()
  const explicitResume = { state: await page.locator('.viewer-toolbar strong').innerText(), url: page.url() }
  await page.goto('http://127.0.0.1:8768/?view=showcase&match=bad')
  const invalid = page.locator('[role="alert"]').filter({ hasText: 'invalid match' })
  await invalid.waitFor()
  check(await invalid.count() === 1, 'Malformed route has duplicate alerts')
  check(await invalid.getByRole('button', { name: 'Watch latest match', exact: true }).count() === 1, 'Recovery action missing')
  await page.screenshot({ path: '/tmp/keisei-ux-fable-fixes/docs/reviews/web-ux-remediation/evidence/fable-invalid-link.png', fullPage: true })
  await invalid.getByRole('button', { name: 'Watch latest match', exact: true }).click()
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  return { rollover, explicitResume, malformedAlertCount: 1, recoveryState: await page.locator('.viewer-toolbar strong').innerText() }
}
