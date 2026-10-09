async (page) => {
  await page.waitForFunction(() => document.body.textContent.includes('Disconnected from server'), null, {timeout:15000})
  return {url:page.url(),connection:await page.locator('[role="alert"]').allTextContents(),retainedGame:await page.locator('.game-info').innerText()}
}
