async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Replay · ply 12$/ }).waitFor()
  check(new URL(page.url()).searchParams.get('match') === '5', 'Paused latest match identity drifted')
  await page.getByRole('button', { name: 'Resume following', exact: true }).click()
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  check(!new URL(page.url()).searchParams.has('match'), 'Resume after rollover did not restore latest feed')
  await page.getByRole('button', { name: 'Copy link to this position', exact: true }).click()
  await page.getByText('Link copied.', { exact: true }).waitFor()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  check(new URL(copied).searchParams.get('match') === '6', 'Resumed board is not the latest actual match')
  return { state: await page.locator('.viewer-toolbar strong').innerText(), viewerUrl: page.url(), copied }
}
