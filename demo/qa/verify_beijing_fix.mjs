import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:8765',out='qa/beijing-fix';
const run=(args,env=process.env)=>execFileSync('.venv/Scripts/python.exe',['run.py',...args],{env,encoding:'utf8'});
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const result={checks:[],requests:[],errors:[]};
const alternateEnv={...process.env,DEMO_STATE_DIR:path.resolve('qa/.tmp/beijing-fix-runtime'),DEMO_DB_PATH:path.resolve('qa/.tmp/beijing-fix.sqlite3')};
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>result.errors.push(e.message));
  page.on('response',r=>{if(r.url().endsWith('/beijing/report'))result.requests.push({url:r.url(),status:r.status()})});
  // No network mocks for the real successful user path.
  await page.goto(base,{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'查我的家乡'}).click();
  const select=async()=>{await page.getByRole('button',{name:'选择北京',exact:true}).click()};
  const loaded=async()=>{await page.getByRole('button',{name:'打开立春档案',exact:true}).waitFor();assert.equal(await page.locator('.term-card').count(),24)};
  await select();await loaded();
  const report=await (await fetch(base+'/api/v1/cities/beijing/report')).json();
  assert.equal(report.city.id,'beijing');assert.equal(report.is_demo,false);
  assert.equal(await page.locator('.report-summary').innerText(),report.summary);
  assert.deepEqual(report.terms.reduce((a,t)=>{a[t.status]=(a[t.status]||0)+1;return a},{}),{alive:9,critical:14,departed:1});
  await page.screenshot({path:out+'/fixed-beijing.png',fullPage:true});
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
  await page.locator('.chart svg').waitFor();
  assert.equal(await page.locator('.detail-score strong').innerText(),report.terms[0].score_display);
  await page.screenshot({path:out+'/fixed-detail.png'});
  await page.locator('.chart-section').scrollIntoViewIfNeeded();
  await page.screenshot({path:out+'/fixed-evidence.png'});
  await page.getByRole('button',{name:'关闭立春档案'}).click();
  result.checks.push('background_launcher_exited_but_real_report_and_detail_work');
  for(const city of ['哈尔滨','西安','上海','成都','广州']){await page.getByRole('button',{name:`选择${city}`,exact:true}).click();await page.getByRole('heading',{name:'尚未接入真实数据',exact:true}).waitFor()}
  await page.getByRole('button',{name:'进入独立样例'}).click();await loaded();
  assert.ok((await page.locator('.demo-notice').innerText()).includes('演示样例，非真实气候结论'));
  result.checks.push('five_unconnected_cities_and_independent_demo_preserved');
  const pattern='**/cities/beijing/report';
  const checkFailure=async(handler,expected)=>{
    await page.route(pattern,handler);await select();
    await page.getByRole('alert').filter({hasText:expected}).waitFor();
    assert.equal(await page.locator('.term-card').count(),0);await page.unroute(pattern);
  };
  for(const [status,code,message] of [[404,'report_missing','北京报告文件缺失'],[500,'report_parse_failed','北京报告解析失败'],[404,'unknown_city','城市不存在']]){
    await checkFailure(r=>r.fulfill({status,contentType:'application/json',body:JSON.stringify({detail:{code,message}})}),message);result.checks.push(code);
  }
  await checkFailure(r=>r.fulfill({status:200,contentType:'application/json',body:'{broken'}),'北京报告解析失败');
  result.checks.push('invalid_response_json_not_mislabeled_as_network_error');
  const incomplete=structuredClone(report);delete incomplete.terms[0].metrics;
  await checkFailure(r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(incomplete)}),'北京报告字段不兼容');
  result.checks.push('incompatible_fields_not_mislabeled_as_network_error');
  await checkFailure(r=>r.abort('failed'),'本机服务仍在运行');
  result.checks.push('blocked_request_distinguished_from_stopped_service');
  run(['--stop']);await select();await page.getByRole('alert').filter({hasText:'本机服务未启动、已关闭'}).waitFor();
  run(['--background','--no-browser']);await page.getByRole('button',{name:'重新尝试'}).click();await loaded();
  result.checks.push('real_service_stop_classified_and_restart_retry_recovers');
  // With 8765 occupied, a separate instance must use its actual selected port.
  const launch=run(['--background','--no-browser'],alternateEnv);
  const alternate=launch.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];assert.ok(alternate);assert.notEqual(alternate,base);
  const second=await browser.newPage();const requests=[];second.on('request',r=>{if(r.url().includes('/api/'))requests.push(r.url())});
  await second.goto(alternate);await second.getByRole('button',{name:'查我的家乡'}).click();await second.getByRole('button',{name:'选择北京',exact:true}).click();await second.getByRole('button',{name:'打开立春档案',exact:true}).waitFor();
  assert.equal(await second.locator('.term-card').count(),24);assert.ok(requests.every(url=>url.startsWith(alternate+'/')));
  result.alternate_url=alternate;result.checks.push('fallback_port_uses_same_origin_api');
  await second.close();run(['--stop'],alternateEnv);
  assert.deepEqual(result.errors,[]);result.passed=true;result.frontend=await (await fetch(base)).text();
  result.frontend=result.frontend.match(/\/assets\/index-[^" ]+\.js/)?.[0];
  await fs.writeFile(out+'/verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{try{run(['--stop'],alternateEnv)}catch{}await browser.close()}
