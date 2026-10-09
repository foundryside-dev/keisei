async(page)=>{
 const results={};const base='http://127.0.0.1:8767';
 await page.goto(base+'/?view=showcase');await page.getByRole('button',{name:'Pause following',exact:true}).waitFor();
 await page.getByRole('button',{name:'Next ply',exact:true}).focus();await page.keyboard.press('Space');
 await page.getByRole('region',{name:'Replay keyboard controls',exact:true}).focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Shift+ArrowRight');
 results.forwardAtTail={label:await page.locator('.viewer-toolbar strong').textContent(),url:page.url()};
 if(results.forwardAtTail.label!=='Live'||new URL(page.url()).searchParams.has('ply'))throw new Error('Forward step pinned the live tail');
 await page.goto(base+'/?view=showcase&match=3&ply=bad');await page.locator('.notice[role="alert"]').waitFor();
 results.invalid={retry:await page.getByRole('button',{name:'Retry saved match',exact:true}).count(),message:await page.locator('.notice[role="alert"]').innerText()};
 if(results.invalid.retry!==0)throw new Error('Invalid route offers no-op Retry');
 await page.getByRole('button',{name:'Watch latest match',exact:true}).click();await page.getByRole('button',{name:'Pause following',exact:true}).waitFor();
 await page.goto(base+'/?view=showcase&match=1');await page.locator('.footer-strip').waitFor();
 results.finished={footer:await page.locator('.footer-strip').textContent()};if(results.finished.footer.includes('to move'))throw new Error('Terminal match claims a next turn');
 await page.route('**/api/showcase/games/2',route=>route.abort('failed'));await page.goto(base+'/?view=showcase&match=2');
 await page.getByRole('button',{name:'Retry saved match',exact:true}).waitFor();await page.unroute('**/api/showcase/games/2');await page.getByRole('button',{name:'Retry saved match',exact:true}).click();await page.locator('.viewer-toolbar strong').waitFor();
 results.requestRetry={label:await page.locator('.viewer-toolbar strong').textContent()};
 if(!results.requestRetry.label.startsWith('Replay'))throw new Error('Request error retry failed');
 await page.goto(base+'/?view=showcase');await page.getByRole('button',{name:'Pause following',exact:true}).waitFor();
 await page.getByRole('button',{name:'Next ply',exact:true}).click();
 return results;
}
