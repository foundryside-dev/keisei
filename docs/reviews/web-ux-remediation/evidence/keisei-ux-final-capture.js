async(page)=>{
 const results=[]
 for(const view of ['training','league','showcase'])for(const theme of ['dark','light'])for(const [width,height] of [[1440,900],[390,844]]){
  await page.setViewportSize({width,height});await page.goto(`http://127.0.0.1:8765/?view=${view}`)
  await page.getByText('connected',{exact:true}).waitFor()
  if(await page.locator('html').getAttribute('data-theme')!==theme)await page.getByRole('button',{name:`Toggle ${theme} theme`}).click()
  if(view==='showcase')await page.getByRole('button',{name:'Pause following',exact:true}).waitFor()
  if(view==='training')await page.locator('#game-panel .board').waitFor()
  if(view==='league')await page.getByRole('heading',{name:/Elo Leaderboard/}).waitFor()
  await page.waitForTimeout(250)
  await page.screenshot({path:`output/playwright/final-${view}-${theme}-${width}x${height}.png`})
  const targets=await page.locator('button:not([disabled])').evaluateAll(es=>es.filter(e=>e.getClientRects().length&&!e.closest('[aria-hidden="true"]')).map(e=>({label:e.getAttribute('aria-label')||e.textContent.trim(),width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})).filter(e=>e.width<44||e.height<44))
  results.push({view,theme,width,height,undersizedTargets:targets})
 }
 return results
}
