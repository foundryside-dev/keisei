async (page) => {
  for (let pages = 0; pages < 10; pages++) {
    const button = page.getByRole('button', { name: 'Load 5 older evaluations', exact: true })
    await button.click()
    await page.waitForFunction(() => !document.querySelector('.load-history')?.disabled)
  }
  const epochs = await page.locator('.gauntlet-epoch .epoch-header').allTextContents()
  const rows = await page.locator('.gauntlet-row').count()
  if (epochs.length !== 51 || new Set(epochs).size !== 51 || rows !== 255) throw new Error(`Whole-history count wrong: epochs ${epochs.length},rows ${rows}`)
  if (!(await page.locator('.historical-library').textContent()).includes('End of evaluation history')) throw new Error('Missing history end state')
  await page.locator('.historical-library-wrapper').evaluate(el => { el.scrollTop = el.scrollHeight - el.clientHeight })
  const before = await page.locator('.historical-library-wrapper').evaluate(el => ({scrollTop:el.scrollTop,scrollHeight:el.scrollHeight}))
  return { epochs: epochs.length, uniqueEpochs: new Set(epochs).size, rows, oldest: epochs.at(-1), beforeLiveScroll:before }
}
