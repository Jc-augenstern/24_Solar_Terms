import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const phase=process.argv[2]||'demo';
const base=process.argv[3]||'http://127.0.0.1:8765';
await fs.mkdir(path.join(root,'screenshots'),{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true,...(phase==='offline'?{storageState:path.join(root,'browser-state.json')}:{})});
const blocked=[],errors=[];
await context.route('**/*',route=>{const url=new URL(route.request().url());if(['127.0.0.1','localhost'].includes(url.hostname))return route.continue();blocked.push(url.href);return route.abort()});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
async function screen(name){await page.screenshot({path:path.join(root,'screenshots',name+'.png'),fullPage:!(await page.locator('dialog[open]').count())})}
async function check(condition,message){assert.ok(condition,message)}
async function png(name){
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('link',{name:'保存 PNG 图片 ↓'}).click();
  const download=await downloadEvent;assert.equal(await download.failure(),null);
  const target=path.join(root,name);await download.saveAs(target);
  const bytes=await fs.readFile(target);assert.equal(bytes.readUInt32BE(16),1080);assert.equal(bytes.readUInt32BE(20),1440);
  return target;
}
try{
  await page.goto(base,{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'查我的家乡'}).waitFor();
  if(phase==='demo')await screen('01-入口');
  await page.getByRole('button',{name:'查我的家乡'}).click();
  if(phase==='demo'){
    await page.getByRole('button',{name:'选择上海',exact:true}).click();
    await page.getByRole('heading',{name:'尚未接入真实数据',exact:true}).waitFor();
    await screen('02-尚未接入');
  }
  const city=phase==='real'?'beijing':'demo';
  await page.getByRole('button',{name:city==='demo'?'进入独立样例':'选择北京',exact:city!=='demo'}).click();
  await page.locator('.term-card').first().waitFor();
  assert.equal(await page.locator('.term-card').count(),24);
  const report=await (await context.request.get(`${base}/api/v1/cities/${city}/report`)).json();
  assert.equal(report.is_demo,city==='demo');
  if(phase!=='offline')await screen(phase==='real'?'05-北京真实名册':'03-演示名册');
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'立春档案',exact:true});
  await dialog.locator('.chart svg').waitFor();
  assert.equal((await dialog.locator('.detail-score strong').innerText()).trim(),report.terms[0].score_display);
  const metricText=await dialog.locator('.metric-card').first().innerText();
  assert.ok(metricText.includes(report.terms[0].metrics[0].baseline.toFixed(2)));
  assert.ok(metricText.includes(report.terms[0].metrics[0].recent.toFixed(2)));
  await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption('precipitation');
  await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption('temperature');
  const exp=await page.evaluate(()=>localStorage.getItem('jieqi-memorial-experience-v1'));
  const endpoint=`${base}/api/v1/cities/${city}/tributes`;
  const before=await (await context.request.get(endpoint+'?experience_id='+exp)).json();
  if(phase==='offline'){
    assert.ok(await page.getByRole('button',{name:'已点亮',exact:true}).isDisabled());
    assert.ok(await page.getByRole('button',{name:'已献花',exact:true}).isDisabled());
    assert.ok(before.total>=2);
    await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
    await page.getByRole('button',{name:'打开雨水档案',exact:true}).click();
    await page.getByRole('button',{name:'点一盏灯',exact:true}).click();
    await page.getByRole('button',{name:'已点亮',exact:true}).waitFor();
    await page.getByRole('button',{name:'关闭雨水档案',exact:true}).click();
  }else{
    await page.getByRole('button',{name:'点一盏灯',exact:true}).click();
    await page.getByRole('button',{name:'已点亮',exact:true}).waitFor();
    await page.getByRole('button',{name:'献一束花',exact:true}).click();
    await page.getByRole('button',{name:'已献花',exact:true}).waitFor();
    const after=await (await context.request.get(endpoint+'?experience_id='+exp)).json();
    assert.equal(after.total,before.total+2);
    const retry=await context.request.post(endpoint,{data:{experience_id:exp,term_id:'lichun',action:'light',idempotency_key:'browser-duplicate-'+phase+'-'+exp}});
    assert.equal(retry.status(),200);assert.equal((await retry.json()).total,after.total);
    await dialog.evaluate(e=>e.scrollTop=0);
    await screen(phase==='real'?'06-北京立春档案':'04-演示档案');
    await dialog.locator('.chart-section').scrollIntoViewIfNeeded();
    await screen(phase==='real'?'10-北京年度证据':'09-演示年度证据');
    await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
  }
  await page.getByRole('button',{name:/生成(城市讣告|家乡守候卡)/}).click();
  await page.getByRole('dialog',{name:'图片预览',exact:true}).waitFor();
  const poster=await png(phase==='real'?'beijing-poster.png':phase==='offline'?'offline-poster.png':'demo-poster.png');
  await page.getByRole('button',{name:'关闭图片预览',exact:true}).click();
  if(phase==='demo'){
    await context.storageState({path:path.join(root,'browser-state.json')});
    await page.reload({waitUntil:'networkidle'});await page.getByRole('button',{name:'查我的家乡'}).click();await page.getByRole('button',{name:'进入独立样例'}).click();await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
    assert.ok(await page.getByRole('button',{name:'已点亮',exact:true}).isDisabled());
    assert.ok(await page.getByRole('button',{name:'已献花',exact:true}).isDisabled());
    await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    await screen('07-窄屏名册');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
    assert.ok(await page.getByRole('dialog',{name:'立春档案',exact:true}).evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await screen('08-窄屏档案');
  }
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
  const result={passed:true,phase,url:base,poster,console_errors:errors,external_requests:blocked,score_display:report.terms[0].score_display,status:report.terms[0].status};
  await fs.writeFile(path.join(root,`browser-${phase}.json`),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
}finally{await browser.close()}
