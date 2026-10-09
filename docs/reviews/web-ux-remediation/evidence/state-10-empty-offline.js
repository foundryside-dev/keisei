async (page) => {
  await page.waitForFunction(() => document.querySelector('.connection')?.textContent === 'connected' && document.querySelector('#game-panel .no-game'), null, {timeout:45000})
  const empty = await page.evaluate(() => ({url:location.href,text:document.querySelector('#game-panel .no-game').textContent,status:document.querySelector('#training-main > [role="status"]').textContent,thumbnails:document.querySelectorAll('.thumbnail').length}))
  if (empty.thumbnails !== 0 || !empty.status.includes('No training lanes available.')) throw new Error('Empty snapshot kept stale selection')
  if (!empty.text.includes('Connect a training session')) throw new Error('Empty view missing recovery action')
  await page.getByRole('tab', {name:'Watch match',exact:true}).click()
  await page.waitForFunction(() => document.querySelector('.offline-banner'))
  const offline = {text:await page.locator('.offline-banner').textContent(),boardPresent:await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).isVisible()}
  if (!offline.boardPresent || !offline.text.toLowerCase().includes('offline')) throw new Error('Offline sidecar lost retained viewer or useful status')
  return {empty,offline}
}
