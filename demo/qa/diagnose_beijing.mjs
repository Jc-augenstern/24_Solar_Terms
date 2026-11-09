import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const network=[], errors=[];
  page.on('requestfailed',r=>network.push({url:r.url(),error:r.failure()}));
  page.on('response',r=>{if(r.url().includes('/api/'))network.push({url:r.url(),status:r.status()})});
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2]||'http://127.0.0.1:8765',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'查我的家乡'}).click();
  if(process.argv.includes('--disconnect'))execFileSync('.venv/Scripts/python.exe',['run.py','--stop']);
  await page.getByRole('button',{name:'选择北京',exact:true}).click();
  await page.locator('.term-card, .error-notice').first().waitFor();
  const result={url:page.url(),cards:await page.locator('.term-card').count(),alerts:await page.getByRole('alert').allTextContents(),network,errors};
  if(result.cards===24){await page.getByRole('button',{name:'打开立春档案',exact:true}).click();await page.locator('.chart svg').waitFor();result.detail=await page.locator('.detail-heading').innerText()}
  await fs.mkdir('qa/beijing-fix',{recursive:true});
  const suffix=process.argv.includes('--disconnect')?'disconnect':'running';
  await page.screenshot({path:`qa/beijing-fix/before-${suffix}.png`,fullPage:false});
  await fs.writeFile(`qa/beijing-fix/diagnosis-${suffix}.json`,JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
}finally{await browser.close()}
