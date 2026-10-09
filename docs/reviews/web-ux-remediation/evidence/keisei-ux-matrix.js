async (page) => {
  const results=[]
  for (const view of ['training','showcase','league']) {
    for (const [width,height] of [[1920,1080],[1440,900],[1280,800],[768,1024],[390,844],[320,568],[844,390]]) {
      await page.setViewportSize({width,height})
      await page.goto(`http://127.0.0.1:8765/?view=${view}`)
      await page.getByText('connected',{exact:true}).waitFor()
      if(await page.locator('html').getAttribute('data-theme')!=='dark')await page.getByRole('button',{name:'Toggle dark theme'}).click()
      if(view==='training') await page.locator('#game-panel .board .square').last().waitFor()
      if(view==='showcase') await page.getByRole('button',{name:'Pause following',exact:true}).waitFor()
      if(view==='league') await page.getByRole('heading',{name:/Elo Leaderboard/}).waitFor()
      const geometry=await page.evaluate((view)=>{
        const rect = selector=> {const e=document.querySelector(selector);if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right}}
        return {overflow:document.documentElement.scrollWidth>innerWidth,board:rect(view==='training'?'#game-panel .board':'.board-side .board'),whiteTray:rect(view==='training'?'#game-panel .tray.white':'.board-side .tray.white'),blackTray:rect(view==='training'?'#game-panel .tray.black':'.board-side .tray.black'),controls:rect('.scrubber-row'),leaderboard:rect('.league-table-card tbody tr'),viewport:{width:innerWidth,height:innerHeight}}
      },view)
      results.push({view,width,height,...geometry})
      if([[1440,900],[390,844],[320,568]].some(([w,h])=>w===width&&h===height))await page.screenshot({path:`output/playwright/${view}-after-${width}x${height}.png`,fullPage:false})
    }
  }
  return results
}
