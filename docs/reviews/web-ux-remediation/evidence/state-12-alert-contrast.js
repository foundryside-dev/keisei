async (page) => {
  return await page.evaluate(() => {
    const rgba = css => { const values = css.match(/[\d.]+/g).map(Number); return [values[0],values[1],values[2],values[3] ?? 1] }
    const over = (fg,bg) => { const alpha = fg[3]+bg[3]*(1-fg[3]);return [0,1,2].map(i=>(fg[i]*fg[3]+bg[i]*bg[3]*(1-fg[3]))/alpha).concat(alpha) }
    const luminance = rgb => rgb.slice(0,3).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0)
    return [...document.querySelectorAll('.offline-banner,.reconnect-banner')].map(el=>{
      let background=[255,255,255,1]; const ancestors=[]
      for(let node=el;node;node=node.parentElement)ancestors.unshift(node)
      for(const node of ancestors)background=over(rgba(getComputedStyle(node).backgroundColor),background)
      const foreground=over(rgba(getComputedStyle(el).color),background)
      const a=luminance(foreground),b=luminance(background)
      return {selector:el.className,text:el.textContent,foreground:foreground.slice(0,3).map(Math.round),background:background.slice(0,3).map(Math.round),ratio:Number(((Math.max(a,b)+.05)/(Math.min(a,b)+.05)).toFixed(2)),theme:document.documentElement.dataset.theme}
    })
  })
}
