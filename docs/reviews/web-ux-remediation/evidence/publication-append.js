async(page)=>{
 await page.waitForFunction(()=>document.querySelector('input[type="range"]')?.getAttribute('aria-valuetext')==='Stored ply 13');
 const followed={label:await page.locator('.viewer-toolbar strong').textContent(),ply:await page.locator('input[type="range"]').getAttribute('aria-valuetext')};
 if(followed.label!=='Live')throw new Error('Forward no-op failed to retain following after append');
 await page.goto('http://127.0.0.1:8767/?view=training');await page.locator('.game-info').waitFor();
 await page.evaluate(()=>{window.__laneStatus=document.querySelector('#training-main > [role="status"]');window.__laneFirst=window.__laneStatus.firstElementChild;window.__laneChanges=0;window.__laneObserver=new MutationObserver(()=>window.__laneChanges++);window.__laneObserver.observe(window.__laneStatus,{childList:true,subtree:true})});
 return followed;
}
