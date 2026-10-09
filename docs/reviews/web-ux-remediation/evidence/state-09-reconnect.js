async (page) => {
  await page.waitForFunction(() => document.querySelector('.connection')?.textContent === 'connected' && document.querySelector('.game-info')?.textContent.includes('Game 2'), null, {timeout:45000})
  const result = await page.evaluate(() => ({connection:document.querySelector('.connection').textContent,info:document.querySelector('.game-info').innerText,status:document.querySelector('#training-main > [role="status"]').textContent}))
  if (!result.status.includes('Lane 1 is unavailable. Selected lane 2.')) throw new Error('Missing-lane fallback not announced')
  return result
}
