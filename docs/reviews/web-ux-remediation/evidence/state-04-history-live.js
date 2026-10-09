async (page) => {
  await page.waitForFunction(() => document.querySelectorAll('.gauntlet-epoch').length === 52)
  const epochs = await page.locator('.gauntlet-epoch .epoch-header').allTextContents()
  const rows = await page.locator('.gauntlet-row').count()
  const newestRows = await page.locator('.gauntlet-epoch').first().locator('.gauntlet-row').count()
  const scroll = await page.locator('.historical-library-wrapper').evaluate(el => ({scrollTop:el.scrollTop,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,bottomDistance:el.scrollHeight-el.clientHeight-el.scrollTop}))
  if (epochs.length !== 52 || new Set(epochs).size !== 52 || rows !== 260 || newestRows !== 5 || epochs.at(-1) !== 'Epoch 1') throw new Error('Live feed erased, split or duplicated paged history')
  if (scroll.bottomDistance > 2) throw new Error(`Old history scroll moved off the bottom: ${scroll.bottomDistance}`)
  await page.locator('[data-entry-id="1"]').click()
  await page.waitForFunction(() => document.activeElement?.classList.contains('detail-heading'))
  return { epochs:epochs.length,uniqueEpochs:new Set(epochs).size,rows,newest:epochs[0],newestRows,oldest:epochs.at(-1),scroll,entryOpened:{url:page.url(),focus:await page.locator('.detail-heading').textContent()} }
}
