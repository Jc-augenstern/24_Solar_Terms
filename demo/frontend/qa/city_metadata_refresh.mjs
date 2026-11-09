// Targeted metadata-only refresh regression. Uses intercepted APIs, no database.
import {chromium} from '../node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const frontend=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const root=path.dirname(frontend),out=path.join(root,'qa','city-metadata-refresh');
const report=JSON.parse(await fs.readFile(path.join(root,'data/reports/beijing.json'),'utf8'));
const registry=JSON.parse(await fs.readFile(path.join(root,'config/cities.json'),'utf8'));
const server=http.createServer(async(req,res)=>{
  const file=path.resolve(frontend,'dist','.'+(req.url==='/'?'/index.html':new URL(req.url,'http://local').pathname));
  if(!file.startsWith(path.join(frontend,'dist')+path.sep)){res.writeHead(404);res.end();return}
  try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(await fs.readFile(file))}
  catch{res.writeHead(404);res.end()}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const result={checked_at:new Date().toISOString(),scope:'Current production build with city metadata API fault injection. Beijing report read-only; no report publication or database access.',checks:[],errors:[],external_requests:[]};
let cityRequests=0,reportRequests=0;
try{
  await fs.mkdir(out,{recursive:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>result.errors.push(e.message));
  await page.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===base)return route.continue();result.external_requests.push(url.href);return route.abort()});
  await page.route('**/api/**',route=>{
    const pathname=new URL(route.request().url()).pathname;
    const fulfill=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(pathname==='/api/v1/cities'){
      cityRequests++;const failed=cityRequests===2;
      const cities=registry.cities.map(city=>({...city,data_status:city.id==='beijing'?'ready':'not_connected',...(city.id==='beijing'?{update_status:failed?'acquisition_blocked':'ready',reason:failed?'已接入 ERA5 真实再分析报告；最近更新未完成，继续使用上一份有效报告。QA测试：共享额度受阻。':'已接入 ERA5 真实再分析报告',update_reason:failed?'QA测试：共享额度受阻。':null}:{})}));
      return fulfill({cities,demo:{id:'demo',name:'样例城',data_status:'demo'}});
    }
    if(pathname==='/api/v1/cities/beijing/report'){reportRequests++;return fulfill(report)}
    if(pathname.endsWith('/tributes'))return fulfill({total:0,light:0,flower:0,terms:{},recorded:[]});
    return fulfill({ok:true});
  });
  await page.goto(base);await page.getByRole('button',{name:'查我的家乡'}).click();
  await page.getByRole('button',{name:'选择北京',exact:true}).click();await page.locator('.term-card').first().waitFor();
  const firstCard=await page.locator('.term-card').first().elementHandle();
  assert.equal(await page.locator('.update-status').count(),0);assert.equal(reportRequests,1);
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.locator('.update-status').filter({hasText:'最近更新未完成，继续使用上一份有效报告'}).waitFor();
  result.failure_warning=await page.locator('.update-status').innerText();
  assert.ok(result.failure_warning.includes('QA测试：共享额度受阻'));
  assert.equal(await page.locator('.report-summary').innerText(),report.summary);
  assert.ok((await page.locator('.archive-heading h1').innerText()).startsWith('北京'));
  assert.equal(await firstCard.evaluate(element=>element===document.querySelector('.term-card')),true);
  assert.equal(reportRequests,1);
  result.checks.push('refresh_updates_selected_city_failure_metadata_and_keeps_existing_report_and_selection');
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.update-status'));
  assert.equal(await page.locator('.report-summary').innerText(),report.summary);assert.equal(reportRequests,1);assert.equal(cityRequests,3);
  result.checks.push('subsequent_successful_metadata_refresh_removes_stale_failure_warning_without_refetch');
  result.city_requests=cityRequests;result.report_requests=reportRequests;
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external_requests,[]);result.passed=true;
  result.production_fix_required=false;
}catch(error){result.passed=false;result.failure={message:error.message,stack:error.stack};process.exitCode=1}
finally{await browser.close();await new Promise(resolve=>server.close(resolve));await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))}
