async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.setViewportSize({ width: 1280, height: 900 })
  const resumes = []
  const archiveRequests = []
  const onRequest = request => { if (request.url().includes('/api/showcase/games/')) archiveRequests.push(request.url()) }
  page.on('request', onRequest)
  for (const control of ['Resume following', 'Live', 'Move log', 'End', 'Space']) {
    await page.goto('http://127.0.0.1:8768/?view=showcase')
    await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
    await page.getByRole('button', { name: 'Pause following', exact: true }).click()
    await page.locator('.viewer-toolbar strong').filter({ hasText: /^Paused at ply 12$/ }).waitFor()
    if (control === 'End' || control === 'Space') {
      await page.getByRole('region', { name: 'Replay keyboard controls', exact: true }).focus()
      await page.keyboard.press(control)
    } else if (control === 'Move log') await page.getByRole('button', { name: 'Return to live position', exact: true }).click()
    else await page.getByRole('button', { name: control, exact: true }).click()
    await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
    const url = new URL(page.url())
    check(!url.searchParams.has('match') && !url.searchParams.has('ply'), `${control} pinned an identity`)
    resumes.push({ control, url: page.url(), state: await page.locator('.viewer-toolbar strong').innerText() })
  }
  page.off('request', onRequest)
  check(archiveRequests.length === 0, 'Local pause downloaded an archive')
  await page.goto('http://127.0.0.1:8768/?view=showcase&match=3&ply=9999')
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Paused at ply 12$/ }).waitFor()
  return { resumes, archiveRequests, futurePly: { state: await page.locator('.viewer-toolbar strong').innerText(), status: await page.locator('.notice[role="status"]').innerText() } }
}
