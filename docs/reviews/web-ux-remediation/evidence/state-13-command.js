async (page) => {
  await page.waitForFunction(() => !document.querySelector('.offline-banner'),null,{timeout:15000})
  await page.getByRole('button',{name:'Open match setup form',exact:true}).click()
  await page.getByRole('combobox',{name:'Black player',exact:true}).selectOption('1')
  await page.getByRole('combobox',{name:'White player',exact:true}).selectOption('2')
  await page.evaluate(() => {
    window.__commandStates=[]
    window.__commandObserver=new MutationObserver(() => {const text=document.querySelector('.command-feedback')?.textContent;if(text&&!window.__commandStates.includes(text))window.__commandStates.push(text)})
    window.__commandObserver.observe(document.body,{childList:true,subtree:true,characterData:true})
  })
  await page.getByRole('button',{name:'Start Match',exact:true}).click()
  await page.waitForFunction(() => document.querySelector('.command-feedback')?.textContent.includes('added to the queue'))
  const result = await page.evaluate(() => ({states:window.__commandStates,feedback:document.querySelector('.command-feedback').textContent}))
  if (!result.states.some(text=>text.includes('Waiting for the server to confirm'))) throw new Error('No actual pending feedback was rendered')
  if (!result.feedback.includes('added to the queue')) throw new Error('Actual server acknowledgement missing')
  return result
}
