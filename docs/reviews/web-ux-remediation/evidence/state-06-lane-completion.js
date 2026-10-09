async (page) => {
  await page.waitForFunction(() => document.querySelector('.game-info .result')?.textContent.includes('draw'))
  const result = await page.evaluate(() => ({info:document.querySelector('.game-info').innerText,selected:[...document.querySelectorAll('.thumbnail[aria-pressed="true"]')].map(el=>el.getAttribute('aria-label')),moves:document.querySelector('.move-log').innerText}))
  if (!result.info.includes('Game 1') || !result.info.includes('draw')) throw new Error('Selected lane changed on completion')
  if (!result.moves.includes('P*1b')) throw new Error('Completed lane history erased')
  return result
}
