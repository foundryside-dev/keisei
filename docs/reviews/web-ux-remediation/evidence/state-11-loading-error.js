async (page) => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/showcase/games/1', async route => { await gate; await route.continue() })
  await page.goto('http://127.0.0.1:8766/?view=showcase&match=1&ply=1')
  await page.getByText('Loading saved match…', {exact:true}).waitFor()
  const loading = {text:await page.getByText('Loading saved match…', {exact:true}).textContent(),viewerCount:await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).count()}
  if (loading.viewerCount !== 0) throw new Error('Loading displays an unrelated board')
  release()
  await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).waitFor()
  await page.unroute('**/api/showcase/games/1')
  await page.route('**/api/showcase/games/2', route => route.abort('failed'))
  await page.goto('http://127.0.0.1:8766/?view=showcase&match=2')
  await page.getByRole('button',{name:'Retry saved match',exact:true}).waitFor()
  const failed = {text:await page.locator('.notice[role="alert"]').textContent(),viewerCount:await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).count()}
  if (failed.viewerCount !== 0) throw new Error('Failure displays an unrelated board')
  await page.unroute('**/api/showcase/games/2')
  await page.getByRole('button',{name:'Retry saved match',exact:true}).click()
  await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).waitFor()
  const retry = {url:page.url(),label:await page.locator('.viewer-toolbar strong').textContent(),estimate:await page.locator('.eval-display').textContent()}
  if (!retry.estimate.includes('Estimate unavailable')) throw new Error('Legacy match lacks unavailable estimate')
  await page.goto('http://127.0.0.1:8766/?view=showcase&match=999999')
  await page.getByRole('button',{name:'Retry saved match',exact:true}).waitFor()
  const missing = await page.locator('.notice[role="alert"]').textContent()
  if (!missing.includes('unavailable')) throw new Error('Missing saved match lacks useful recovery')
  await page.getByRole('button',{name:'Watch latest match',exact:true}).click()
  await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).waitFor()
  return {loading,failed,retry,missing,recoveryUrl:page.url(),conditions:'Real server payloads; browser delivery held for loading and browser request aborted for retry; actual HTTP404 for missing match.'}
}
