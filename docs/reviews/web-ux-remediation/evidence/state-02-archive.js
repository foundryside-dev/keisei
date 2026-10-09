async (page) => {
  await page.waitForFunction(() => document.querySelector('.viewer-toolbar strong')?.textContent.includes('Replay · ply 13'))
  const retained = { url: page.url(), label: await page.locator('.viewer-toolbar strong').textContent(), result: await page.getByRole('region', { name: 'Match scorecard' }).textContent() }
  if (!retained.url.includes('match=3&ply=13') || !retained.result.toLowerCase().includes(' draw ')) throw new Error(`Explicit match was not retained with its final result: ${JSON.stringify(retained)}`)
  const latest = await page.evaluate(async () => (await (await fetch('/api/showcase/games/4')).json()).game)
  if (latest.id !== 4 || latest.status !== 'in_progress') throw new Error('Latest match 4 not present')
  await page.getByRole('button', { name: 'Watch latest match', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.viewer-toolbar strong')?.textContent === 'Live')
  if (new URL(page.url()).searchParams.has('match')) throw new Error('Follow latest did not clear archive identity')
  const followed = { url: page.url(), label: await page.locator('.viewer-toolbar strong').textContent(), ply: await page.getByRole('region', { name: 'Match scorecard' }).textContent() }
  return { retained, latest: { id: latest.id, status: latest.status }, followed }
}
