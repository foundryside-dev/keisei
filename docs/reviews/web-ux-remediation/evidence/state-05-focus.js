async (page) => {
  await page.waitForFunction(() => !document.querySelector('[data-entry-id="1"]'))
  const detailBefore = await page.locator('.detail-heading').textContent()
  if (!detailBefore.includes('retired')) throw new Error('Entry retirement not reflected')
  await page.getByRole('button', { name: 'Close entry detail', exact: true }).click()
  await page.waitForFunction(() => document.activeElement?.textContent.includes('Elo Leaderboard'))
  const result = await page.evaluate(() => ({url:location.href,focus:document.activeElement.textContent,status:document.querySelector('#league-main > [role="status"]').textContent}))
  if (!result.status.includes('no longer in the leaderboard')) throw new Error('Missing useful focus fallback announcement')
  return { detailBefore, afterClose:result }
}
