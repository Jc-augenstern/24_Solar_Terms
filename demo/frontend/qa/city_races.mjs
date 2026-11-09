// Frontend fault injection only. This is not evidence of real multi-city coverage.
import {chromium} from '../node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const frontend=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const project=path.dirname(frontend),out=path.join(project,'qa','frontend-city-races');
const beijing=JSON.parse(await fs.readFile(path.join(project,'data/reports/beijing.json'),'utf8'));
const demo=JSON.parse(await fs.readFile(path.join(project,'data/reports/demo.json'),'utf8'));
const registry=JSON.parse(await fs.readFile(path.join(project,'config/cities.json'),'utf8'));
const cities=registry.cities.map(c=>({...c,data_status:c.id==='beijing'?'ready':'not_connected'}));
const server=http.createServer(async(req,res)=>{
  const file=path.resolve(frontend,'dist','.'+(req.url==='/'?'/index.html':new URL(req.url,'http://local').pathname));
  if(!file.startsWith(path.join(frontend,'dist')+path.sep)){res.writeHead(404);res.end();return}
  try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(await fs.readFile(file))}
  catch{res.writeHead(404);res.end()}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const checks=[],errors=[];
let releaseReport,releaseOldTribute,releaseNewTribute;
let delayReport=false;
const empty=()=>({total:0,light:0,flower:0,terms:{},recorded:[]});
const recorded=()=>({total:1,light:1,flower:0,terms:{lichun:{light:1,flower:0}},recorded:[{term_id:'lichun',action:'light'}],recorded_now:true});
try{
  await fs.mkdir(out,{recursive:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    const original=HTMLCanvasElement.prototype.toBlob;
    window.__posterCallbacks=[];
    HTMLCanvasElement.prototype.toBlob=function(callback,...args){original.call(this,blob=>window.__posterCallbacks.push(()=>callback(blob)),...args)};
    window.__releasePosters=()=>window.__posterCallbacks.splice(0).forEach(fn=>fn());
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),pathname=url.pathname;
    const fulfill=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(pathname==='/api/health')return fulfill({ok:true});
    if(pathname==='/api/v1/cities')return fulfill({cities,demo:{id:'demo',name:'样例城',data_status:'demo'}});
    if(pathname.endsWith('/report')){
      if(pathname.includes('/beijing/')&&delayReport){await new Promise(resolve=>{releaseReport=resolve});try{return await fulfill(beijing)}catch{return}}
      if(pathname.includes('/beijing/'))return fulfill(beijing);
      if(pathname.includes('/demo/'))return fulfill(demo);
      return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{code:'not_connected',message:'故障注入：此测试没有该城市真实报告。'}})});
    }
    if(pathname.endsWith('/tributes')){
      if(route.request().method()==='GET')return fulfill(empty());
      if(pathname.includes('/beijing/'))await new Promise(resolve=>{releaseOldTribute=resolve});
      else await new Promise(resolve=>{releaseNewTribute=resolve});
      return fulfill(recorded());
    }
    return fulfill({});
  });
  await page.goto(base);await page.getByRole('button',{name:'查我的家乡'}).click();
  assert.equal(await page.locator('.city-button').count(),34);
  assert.equal(await page.locator('.city-group').count(),4);
  assert.ok(await page.locator('.city-list').evaluate(e=>e.scrollHeight>e.clientHeight));
  await page.getByLabel('搜索城市或省级地区').fill('浙江');
  assert.equal(await page.locator('.city-button').count(),1);assert.equal(await page.locator('.city-button').getAttribute('aria-label'),'选择杭州');
  await page.getByLabel('搜索城市或省级地区').fill('Urumqi');
  assert.equal(await page.locator('.city-button').count(),1);
  await page.getByLabel('搜索城市或省级地区').fill('');
  checks.push('34_registry_entries_grouped_scrollable_and_region_alias_search');
  delayReport=true;
  await page.getByRole('button',{name:'选择北京',exact:true}).click();
  await page.getByRole('button',{name:'进入独立样例'}).click();
  await page.locator('.term-card').first().waitFor();
  assert.ok((await page.locator('.archive-heading h1').innerText()).includes('样例城'));
  releaseReport();await page.waitForTimeout(200);
  assert.ok((await page.locator('.archive-heading h1').innerText()).includes('样例城'));
  assert.equal(await page.locator('.report-summary').innerText(),demo.summary);
  checks.push('late_beijing_report_cannot_replace_new_demo_selection');
  delayReport=false;
  await page.getByRole('button',{name:'选择北京',exact:true}).click();
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
  await page.locator('.chart svg').waitFor();
  assert.equal(await page.locator('.detail-score strong').innerText(),beijing.terms[0].score_display);
  assert.ok((await page.getByRole('link',{name:'坐标核对来源'}).getAttribute('href')).includes('geonames.org'));
  await page.getByRole('button',{name:'点一盏灯',exact:true}).click();
  await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
  await page.getByRole('button',{name:'进入独立样例'}).click();
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
  await page.getByRole('button',{name:'点一盏灯',exact:true}).click();
  releaseOldTribute();await page.waitForTimeout(200);
  assert.equal(await page.getByRole('button',{name:'保存中…',exact:true}).count(),1);
  assert.equal(await page.getByRole('button',{name:'已点亮',exact:true}).count(),0);
  releaseNewTribute();await page.getByRole('button',{name:'已点亮',exact:true}).waitFor();
  checks.push('old_city_tribute_cannot_complete_new_city_pending_action');
  await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
  await page.getByRole('button',{name:'选择北京',exact:true}).click();
  await page.getByRole('button',{name:/生成城市讣告|生成家乡守候卡/}).click();
  await page.waitForFunction(()=>window.__posterCallbacks.length===1);
  await page.getByRole('button',{name:'进入独立样例'}).click();
  await page.locator('.term-card').first().waitFor();
  await page.evaluate(()=>window.__releasePosters());await page.waitForTimeout(100);
  assert.equal(await page.getByRole('dialog',{name:'图片预览'}).count(),0);
  await page.getByRole('button',{name:/生成城市讣告|生成家乡守候卡/}).click();
  await page.waitForFunction(()=>window.__posterCallbacks.length===1);await page.evaluate(()=>window.__releasePosters());
  await page.getByRole('dialog',{name:'图片预览'}).waitFor();
  assert.ok((await page.locator('.poster-preview h2').innerText()).includes('样例城'));
  assert.ok((await page.locator('.poster-preview .demo-notice').innerText()).includes('演示样例'));
  await page.getByRole('button',{name:'关闭图片预览'}).click();
  checks.push('late_poster_discarded_and_new_preview_keeps_own_identity_and_demo_notice');
  await page.setViewportSize({width:390,height:844});
  const select=page.getByRole('combobox',{name:'选择家乡城市'});
  await select.selectOption('beijing');await page.locator('.term-card').first().waitFor();
  assert.equal(await page.locator('.city-list').isVisible(),false);
  assert.equal(await select.locator('option').count(),35);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:path.join(out,'mobile-registry-fixture.png'),fullPage:true});
  checks.push('mobile_search_and_native_34_city_selection_without_horizontal_overflow');
  assert.deepEqual(errors,[]);
  const result={passed:true,scope:'Frontend fault injection; real Beijing and explicit demo reports only, no claim of completed city coverage.',checks,errors};
  await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{releaseReport?.();releaseOldTribute?.();releaseNewTribute?.();await browser.close();await new Promise(resolve=>server.close(resolve))}
