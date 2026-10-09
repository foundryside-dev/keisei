async (page) => {
  const results=[]
  for(const theme of ['dark','light']) {
    for(const [width,height] of [[1440,900],[390,844]]) {
      await page.setViewportSize({width,height})
      await page.goto('http://127.0.0.1:8765/?view=showcase')
      await page.getByRole('button',{name:'Pause following',exact:true}).waitFor()
      if(await page.locator('html').getAttribute('data-theme')!==theme)await page.getByRole('button',{name:`Toggle ${theme} theme`}).click()
      await page.waitForTimeout(250)
      const pairs=await page.evaluate(()=>{
        const parse=c=> {const n=c.match(/[\d.]+/g)?.map(Number)||[];return n.length<3?[0,0,0,0]:[n[0],n[1],n[2],n[3]??1]}
        const over=(a,b)=>[...a.slice(0,3).map((v,i)=>v*a[3]+b[i]*(1-a[3])),1]
        const luminance=c=>c.slice(0,3).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0)
        const contrast=(a,b)=>{const l=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (l[0]+.05)/(l[1]+.05)}
        const background=e=>{let chain=[];for(let n=e;n;n=n.parentElement)chain.push(n);return chain.reverse().reduce((bg,n)=>over(parse(getComputedStyle(n).backgroundColor),bg),[255,255,255,1])}
        const entries=[]
        for(const [name,selector] of [['new-match','.new-match-btn'],['selected-tab','.tab-bar .active'],['selected-speed','.speed-controls button[aria-pressed="true"]'],['board-coordinates','.col-labels'],['viewer-state','.viewer-toolbar strong'],['player-role','.tier'],['analysis-label','.commentary .label'],['graph-label','.win-prob-graph .axis-hint']]){
          const e=document.querySelector(selector);if(!e)continue;const fg=parse(getComputedStyle(e).color),bg=background(e);entries.push({name,foreground:fg,background:bg,ratio:+contrast(over(fg,bg),bg).toFixed(2),minimum:4.5})
        }
        const root=getComputedStyle(document.documentElement),temp=document.createElement('div');document.body.append(temp)
        const color=name=>{temp.style.color=root.getPropertyValue(name);return parse(temp.style.color)}
        for(const [name,fg,bg,minimum] of [['board-grid','--border-board-inner','--bg-board',3],['focus','--focus-ring','--bg-primary',3],['chart-series','--chart-teal','--bg-primary',3],['chart-axis','--text-secondary','--bg-primary',4.5]])entries.push({name,foreground:color(fg),background:color(bg),ratio:+contrast(color(fg),color(bg)).toFixed(2),minimum})
        temp.remove();return entries
      })
      if(pairs.some(pair=>pair.ratio<pair.minimum))throw new Error(JSON.stringify({theme,width,failed:pairs.filter(pair=>pair.ratio<pair.minimum)}))
      results.push({theme,width,height,contrast:pairs})
      await page.screenshot({path:`output/playwright/watch-${theme}-${width}x${height}.png`})
      await page.getByRole('button',{name:'Open match setup form'}).click()
      await page.getByRole('combobox',{name:'Black player',exact:true}).selectOption('1')
      await page.getByRole('combobox',{name:'White player',exact:true}).selectOption('2')
      const action=await page.locator('.start-btn').evaluate(e=>({foreground:getComputedStyle(e).color,background:getComputedStyle(e).backgroundColor,enabled:!e.disabled}))
      results.push({theme,width,primaryAction:action})
      await page.getByRole('button',{name:'Hide match setup form'}).click()
      await page.emulateMedia({reducedMotion:'reduce'})
      await page.evaluate(()=>{
        const sizes=[...document.querySelectorAll('*')].map(e=>[e,Number.parseFloat(getComputedStyle(e).fontSize)])
        for(const [e,size] of sizes)if(size>0)e.style.fontSize=`${size*2}px`
      })
      const enlarged=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,squares:document.querySelectorAll('.board-side .square').length,controls:document.querySelector('.scrubber-row').getBoundingClientRect().width,motion:getComputedStyle(document.querySelector('.square')).transitionDuration}))
      if(enlarged.overflow||enlarged.squares!==81)throw new Error(JSON.stringify({theme,width,enlarged}))
      results.push({theme,width,text200:enlarged})
      await page.screenshot({path:`output/playwright/watch-${theme}-${width}-text200.png`,fullPage:true})
    }
  }
  await page.emulateMedia({reducedMotion:'no-preference'})
  return results
}
