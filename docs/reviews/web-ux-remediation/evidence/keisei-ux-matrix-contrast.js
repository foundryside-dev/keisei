async(page)=>{
const results=[];await page.setViewportSize({width:1440,height:900});
for(const theme of ['dark','light']){
 await page.goto('http://127.0.0.1:8765/?view=league');await page.locator('.rate-cell').first().waitFor({state:'attached'});
 if(await page.locator('html').getAttribute('data-theme')!==theme)await page.getByRole('button',{name:`Toggle ${theme} theme`}).click();await page.waitForTimeout(250);
      const pairs=await page.evaluate(()=>{
        const parse=c=> {const n=c.match(/[\d.]+/g)?.map(Number)||[];return n.length<3?[0,0,0,0]:[n[0],n[1],n[2],n[3]??1]}
        const over=(a,b)=>[...a.slice(0,3).map((v,i)=>v*a[3]+b[i]*(1-a[3])),1]
        const luminance=c=>c.slice(0,3).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0)
        const contrast=(a,b)=>{const l=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (l[0]+.05)/(l[1]+.05)}
        const background=e=>{let chain=[];for(let n=e;n;n=n.parentElement)chain.push(n);return chain.reverse().reduce((bg,n)=>over(parse(getComputedStyle(n).backgroundColor),bg),[255,255,255,1])}
        const entries=[]
        for(const [i,e] of [...document.querySelectorAll('.rate-cell')].entries()){
          const fg=parse(getComputedStyle(e).color),bg=background(e);entries.push({name:'matrix-cell-'+i,foreground:fg,background:bg,ratio:+contrast(over(fg,bg),bg).toFixed(2),minimum:4.5})
        }
        const root=getComputedStyle(document.documentElement),temp=document.createElement('div');document.body.append(temp)
        const color=name=>{temp.style.color=root.getPropertyValue(name);return parse(temp.style.color)}
        for(const [name,fg,bg,minimum] of [['board-grid','--border-board-inner','--bg-board',3],['focus','--focus-ring','--bg-primary',3],['chart-series','--chart-teal','--bg-primary',3],['chart-axis','--text-secondary','--bg-primary',4.5]])entries.push({name,foreground:color(fg),background:color(bg),ratio:+contrast(color(fg),color(bg)).toFixed(2),minimum})
        temp.remove();return entries
      })

 if(pairs.some(p=>p.ratio<p.minimum))throw new Error(JSON.stringify({theme,pairs}));results.push({theme,pairs});
}return results}
