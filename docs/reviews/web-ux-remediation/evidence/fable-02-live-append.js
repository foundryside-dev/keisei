async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  await page.waitForTimeout(700)
  const state = await page.locator('.viewer-toolbar strong').innerText()
  const range = await page.locator('input[type="range"]').evaluate(node => ({ value: node.value, max: node.max }))
  check(state === 'Paused at ply 12' && range.value === '11' && range.max === '12', 'Clamped pause drifted during actual WebSocket append')
  await page.screenshot({ path: '/tmp/keisei-ux-fable-fixes/docs/reviews/web-ux-remediation/evidence/fable-paused-clamp.png', fullPage: true })
  await page.goto('http://127.0.0.1:8768/?view=showcase')
  await page.locator('.viewer-toolbar strong').filter({ hasText: /^Live$/ }).waitFor()
  await page.getByRole('button', { name: 'Pause following', exact: true }).click()
  await page.getByRole('button', { name: 'Resume following', exact: true }).click()
  check(new URL(page.url()).searchParams.get('match') === null, 'Resume left explicit match')
  return { afterActualAppend: { state, range }, readyForNewMatch: page.url() }
}
