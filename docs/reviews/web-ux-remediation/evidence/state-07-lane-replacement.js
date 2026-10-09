async (page) => {
  await page.waitForFunction(() => document.querySelector('#training-main > [role="status"]')?.textContent.includes('New game in lane 1'))
  const result = await page.evaluate(() => ({info:document.querySelector('.game-info').innerText,announcement:document.querySelector('#training-main > [role="status"]').textContent,moves:document.querySelector('.move-log').innerText,board:document.querySelector('#game-panel [role="img"]').getAttribute('aria-label')}))
  if (!result.info.includes('Game 1') || !result.info.includes('Ply\n0') || !result.info.includes('In progress')) throw new Error(`Replacement lane did not reset: ${result.info}`)
  if (result.moves.includes('P*1b')) throw new Error('Previous game moves leaked into replacement')
  if (!result.board.includes('black to move')) throw new Error('Replacement starting side wrong')
  return result
}
