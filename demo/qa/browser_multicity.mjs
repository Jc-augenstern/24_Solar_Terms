/** Real Chrome + delivered Windows launcher, using isolated data for every tribute.
 * Blocks external requests in the browser; offline phase additionally blocks
 * non-loopback sockets in the actual Python application process.
 */
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {execFileSync, spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'qa','multicity');
const runId=new Date().toISOString().replace(/[:.]/g,'-');
const temp=path.join(out,'runs',runId);
await fs.mkdir(temp,{recursive:true});
const env={...process.env,DEMO_STATE_DIR:path.join(temp,'runtime'),DEMO_DB_PATH:path.join(temp,'tributes.sqlite3')};
const python=path.join(root,'.venv','Scripts','python.exe');
const result={checked_at:new Date().toISOString(),test_database:env.DEMO_DB_PATH,checks:[],cities:[],errors:[],external_requests:[]};
const run=(args,extra=env)=>execFileSync(python,['-X','utf8',path.join(root,'run.py'),...args],{cwd:root,env:extra,encoding:'utf8',windowsHide:true,timeout:30000});
const launchCmd=name=>execFileSync('cmd.exe',['/d','/c',path.join(root,name)],{cwd:root,env,encoding:'utf8',windowsHide:true,timeout:30000});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function baseFromState(){
  for(let i=0;i<100;i++){
    try{
      const s=JSON.parse(await fs.readFile(path.join(env.DEMO_STATE_DIR,'server.json'),'utf8'));
      const base=`http://127.0.0.1:${s.port}`;
      const health=await fetch(base+'/api/health').then(r=>r.json());
      if(health.ok&&health.instance_id===s.instance_id)return base;
    }catch{}
    await wait(100);
  }
  throw new Error('Isolated launcher did not become ready');
}
async function choose(page,city){
  const search=page.getByRole('searchbox');
  if(await search.count())await search.fill('');
  await page.getByRole('button',{name:`选择${city.name}`,exact:true}).click();
}
async function loaded(page,report){
  await page.getByRole('button',{name:'打开立春档案',exact:true}).waitFor();
  assert.equal(await page.locator('.term-card').count(),24);
  assert.ok((await page.locator('.archive-heading h1').innerText()).startsWith(report.city.name));
  assert.equal(await page.locator('.report-summary').innerText(),report.summary);
  assert.equal(await page.locator('.term-card').first().locator('.term-score strong').innerText(),report.terms[0].score_display);
}
async function installCanvasAudit(page){
  await page.evaluate(()=>{
    window.qaCanvasTexts=[];
    const original=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.qaCanvasTexts.push(String(text));return original.call(this,text,...args)};
  });
}
async function savePoster(page,city,phase){
  await page.evaluate(()=>window.qaCanvasTexts=[]);
  await page.getByRole('button',{name:/生成(城市讣告|家乡守候卡)/}).click();
  const dialog=page.getByRole('dialog',{name:'图片预览',exact:true});await dialog.waitFor();
  assert.ok((await dialog.locator('h2').innerText()).includes(city.name));
  const text=await page.evaluate(()=>window.qaCanvasTexts.join('\n'));
  assert.ok(text.includes(city.name)&&text.includes('1961')&&text.includes('1996')&&text.includes('ERA5'));
  for(const term of city.report.terms)assert.ok(text.includes(term.name),`${city.name} poster missing ${term.name}`);
  if(city.id!=='beijing')assert.ok(!text.includes('北京'));
  const event=page.waitForEvent('download');
  await page.getByRole('link',{name:'保存 PNG 图片 ↓'}).click();
  const download=await event;assert.equal(await download.failure(),null);
  assert.ok(download.suggestedFilename().includes(city.name));
  const target=path.join(out,`${city.id}-${phase}-poster.png`);await download.saveAs(target);
  const bytes=await fs.readFile(target);assert.equal(bytes.readUInt32BE(16),1080);assert.equal(bytes.readUInt32BE(20),1440);
  await fs.writeFile(path.join(out,`${city.id}-${phase}-poster-text.json`),JSON.stringify({city:city.id,text},null,2));
  await page.getByRole('button',{name:'关闭图片预览',exact:true}).click();return target;
}
async function checkCity(page,context,base,city,phase){
  await choose(page,city);await loaded(page,city.report);
  if(phase==='online'){
    const filters=page.getByRole('group',{name:'筛选节气状态'});
    for(const [status,label] of [['alive','健在'],['critical','病危'],['departed','已故'],['insufficient_data','资料不足']]){
      await filters.getByRole('button',{name:new RegExp(label)}).click();
      assert.equal(await page.locator('.term-card').count(),city.report.terms.filter(t=>t.status===status).length);
    }
    await filters.getByRole('button',{name:/全部/}).click();
  }
  if(phase==='online')await page.screenshot({path:path.join(out,`${city.id}-roster.png`),fullPage:true});
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'立春档案',exact:true});await dialog.locator('.chart svg').waitFor();
  assert.ok((await dialog.locator('.eyebrow').first().innerText()).includes(city.name));
  assert.equal(await dialog.locator('.detail-score strong').innerText(),city.report.terms[0].score_display);
  await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption('precipitation');
  await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption('diurnal_range');
  await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption('temperature');
  assert.ok(await dialog.locator('.chart svg path').count()>0);
  const exp=await page.evaluate(()=>localStorage.getItem('jieqi-memorial-experience-v1'));
  const endpoint=`${base}/api/v1/cities/${city.id}/tributes`;
  const before=await context.request.get(`${endpoint}?experience_id=${exp}`).then(r=>r.json());
  if(phase==='online'){
    assert.equal(before.total,0,`${city.name} must not inherit another city's same-term actions`);
    for(const [action,label,done] of [['light','点一盏灯','已点亮'],['flower','献一束花','已献花']]){
      await page.getByRole('button',{name:label,exact:true}).click();
      await page.getByRole('button',{name:done,exact:true}).waitFor();
      assert.ok(await page.getByRole('button',{name:done,exact:true}).isDisabled());
      const duplicate=await context.request.post(endpoint,{data:{experience_id:exp,term_id:'lichun',action,idempotency_key:`qa-${city.id}-${action}-${runId}`}});
      assert.equal(duplicate.status(),200);assert.equal((await duplicate.json()).recorded_now,false);
    }
    await dialog.evaluate(e=>e.scrollTop=0);await page.screenshot({path:path.join(out,`${city.id}-detail.png`)});
    await dialog.locator('.chart-section').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`${city.id}-chart.png`)});
  }else{
    assert.equal(before.total,2);
    assert.ok(await page.getByRole('button',{name:'已点亮',exact:true}).isDisabled());
    assert.ok(await page.getByRole('button',{name:'已献花',exact:true}).isDisabled());
  }
  await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
  if(phase==='offline'){
    // Prove that cold-start offline mode supports new writes, not just old counts.
    await page.getByRole('button',{name:'打开雨水档案',exact:true}).click();
    let expectedTotal=before.total;
    for(const [action,label,done] of [['light','点一盏灯','已点亮'],['flower','献一束花','已献花']]){
      await page.getByRole('button',{name:label,exact:true}).click();
      await page.getByRole('button',{name:done,exact:true}).waitFor();
      assert.ok(await page.getByRole('button',{name:done,exact:true}).isDisabled());
      expectedTotal++;
      const saved=await context.request.get(`${endpoint}?experience_id=${exp}`).then(r=>r.json());
      assert.equal(saved.total,expectedTotal);assert.equal(saved.terms.yushui[action],1);
      const duplicate=await context.request.post(endpoint,{data:{experience_id:exp,term_id:'yushui',action,idempotency_key:`qa-offline-${city.id}-${action}-${runId}`}});
      assert.equal(duplicate.status(),200);const retried=await duplicate.json();
      assert.equal(retried.recorded_now,false);assert.equal(retried.total,expectedTotal);
    }
    await page.locator('.tribute-section').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,`${city.id}-offline-new-tributes.png`)});
    await page.getByRole('button',{name:'关闭雨水档案',exact:true}).click();
  }
  const poster=await savePoster(page,city,phase);
  return {id:city.id,name:city.name,phase,report_id:city.report.report_id,generated_at:city.report.generated_at,page:'passed',chart:'passed',memorial:'passed',offline_new_writes:phase==='offline'?'passed':'not_applicable',poster:'passed',poster_file:poster};
}

// Generate the explicit synthetic fixture in a fresh checkout; never alter real reports.
execFileSync(python,['-X','utf8',path.join(root,'qa','make_edge_fixture.py')],{cwd:root,env,encoding:'utf8',windowsHide:true,timeout:30000});

let browser,blocker,offline,onlineContext;
try{
  // Force the delivered launcher onto a safe alternate port, unless another
  // application already owns 8765. This test never stops that other application.
  blocker=net.createServer(socket=>socket.end());
  const owned=await new Promise(resolve=>{blocker.once('error',()=>resolve(false));blocker.listen(8765,'127.0.0.1',()=>resolve(true))});
  result.default_port_test={test_listener_owned:owned};
  result.launcher_stdout=launchCmd('启动作品.cmd');
  const base=await baseFromState();assert.notEqual(base,'http://127.0.0.1:8765');
  result.actual_url=base;result.checks.push('actual_start_cmd_returns_and_background_service_remains','occupied_default_port_uses_alternate');
  const registry=await fetch(base+'/api/v1/cities').then(r=>r.json());
  assert.equal(registry.cities.length,34);
  const cities=[];
  for(const city of registry.cities.filter(c=>c.data_status==='ready'))cities.push({...city,report:await fetch(`${base}/api/v1/cities/${city.id}/report`).then(r=>r.json())});
  result.actual_real_coverage=cities.length;result.city_statuses=registry.cities.map(({id,name,data_status,reason})=>({id,name,data_status,reason}));
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  async function newContext(storageState){
    const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true,...(storageState?{storageState}:{})});
    await context.route('**/*',route=>{const u=new URL(route.request().url());if(['127.0.0.1','localhost'].includes(u.hostname)||['blob:','data:'].includes(u.protocol))return route.continue();result.external_requests.push(u.href);return route.abort()});
    return context;
  }
  onlineContext=await newContext();const page=await onlineContext.newPage();page.on('pageerror',e=>result.errors.push(e.message));
  const requests=[];page.on('request',r=>{if(r.url().includes('/api/'))requests.push(r.url())});
  await page.goto(base,{waitUntil:'networkidle'});await page.getByRole('button',{name:'查我的家乡'}).click();
  await installCanvasAudit(page);
  for(const city of cities)result.cities.push(await checkCity(page,onlineContext,base,city,'online'));
  result.unavailable_cities=[];
  for(const city of registry.cities.filter(c=>c.data_status!=='ready')){
    await choose(page,city);await page.getByRole('alert').waitFor();
    assert.equal(await page.locator('.term-card').count(),0);
    assert.ok((await page.locator('.unavailable-state').innerText()).includes(city.name));
    result.unavailable_cities.push({id:city.id,name:city.name,entry:'passed',data_status:city.data_status,reason:city.reason});
    if(['haikou','lhasa','urumqi','chongqing','taipei','hongkong','macau'].includes(city.id))await page.screenshot({path:path.join(out,`${city.id}-unavailable.png`),fullPage:true});
  }
  result.checks.push('all_34_entries_show_real_availability_without_sample_fallback');
  assert.ok(requests.every(url=>url.startsWith(base+'/')));result.checks.push('all_api_requests_follow_actual_port');
  // Region search must locate the corresponding city without separate frontend lists.
  const search=page.getByRole('searchbox');
  if(await search.count()){
    await search.fill('新疆');await page.getByRole('button',{name:'选择乌鲁木齐',exact:true}).waitFor();
    await search.fill('香港');await page.getByRole('button',{name:'选择香港',exact:true}).waitFor();
    await search.fill('');result.checks.push('region_and_city_search');
  }
  if(cities.length>=2){
    const [first,second]=cities;
    const pattern=`**/cities/${first.id}/report`;
    await page.route(pattern,async route=>{await wait(700);try{await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(first.report)})}catch{}});
    await choose(page,first);await choose(page,second);await loaded(page,second.report);await wait(900);await loaded(page,second.report);await page.unroute(pattern);
    result.checks.push('late_old_report_cannot_overwrite_new_city');
    await page.evaluate(()=>{window.qaOriginalBlob=HTMLCanvasElement.prototype.toBlob;HTMLCanvasElement.prototype.toBlob=function(cb,...args){return window.qaOriginalBlob.call(this,b=>setTimeout(()=>cb(b),700),...args)}});
    await choose(page,first);await loaded(page,first.report);await page.getByRole('button',{name:/生成(城市讣告|家乡守候卡)/}).click();await choose(page,second);await loaded(page,second.report);await wait(1000);
    assert.equal(await page.getByRole('dialog',{name:'图片预览',exact:true}).count(),0);
    await page.evaluate(()=>HTMLCanvasElement.prototype.toBlob=window.qaOriginalBlob);result.checks.push('late_old_poster_cannot_appear_after_city_switch');
  }
  const beijing=cities.find(c=>c.id==='beijing');assert.ok(beijing);
  await choose(page,beijing);await loaded(page,beijing.report);
  const pattern='**/cities/beijing/report';
  async function failure(handler,message){await page.route(pattern,handler);await choose(page,beijing);await page.getByRole('alert').filter({hasText:message}).waitFor();assert.equal(await page.locator('.term-card').count(),0);await page.unroute(pattern)}
  for(const [status,code,message] of [[404,'report_missing','北京报告文件缺失'],[500,'report_parse_failed','北京报告解析失败'],[500,'report_schema_mismatch','北京报告字段不兼容']]){
    await failure(r=>r.fulfill({status,contentType:'application/json',body:JSON.stringify({detail:{code,message}})}),message);result.checks.push(code);
  }
  await failure(r=>r.fulfill({status:200,contentType:'application/json',body:'{invalid'}),'解析失败');
  await failure(r=>r.abort('failed'),'本机服务仍在运行');result.checks.push('invalid_json_and_interrupted_request_not_mislabeled_as_connection');
  // Preserve the deliberately independent demo boundary and quality edge states.
  await page.getByRole('button',{name:'进入独立样例'}).click();await page.locator('.term-card').first().waitFor();
  assert.ok((await page.locator('.demo-notice').first().innerText()).includes('演示样例，非真实气候结论'));
  await page.getByRole('group',{name:'筛选节气状态'}).getByRole('button',{name:/资料不足/}).click();
  assert.equal(await page.locator('.term-card').count(),1);
  await page.getByRole('button',{name:'打开大寒档案',exact:true}).click();
  assert.equal(await page.locator('.detail-score strong').innerText(),'—');
  assert.ok((await page.locator('.detail-summary').innerText()).includes('不足27年'));
  await page.getByRole('button',{name:'关闭大寒档案',exact:true}).click();result.checks.push('insufficient_data_remains_unrated_and_separate_from_acquisition');
  await page.getByRole('group',{name:'筛选节气状态'}).getByRole('button',{name:/全部/}).click();
  // Export the actual independent demo while it still contains insufficient data.
  await page.evaluate(()=>window.qaCanvasTexts=[]);
  await page.getByRole('button',{name:/生成(城市讣告|家乡守候卡)/}).click();
  await page.getByRole('dialog',{name:'图片预览',exact:true}).waitFor();
  const insufficientTexts=await page.evaluate(()=>window.qaCanvasTexts);
  assert.ok(insufficientTexts.includes('演示样例，非真实气候结论'));
  assert.ok(insufficientTexts.some(t=>t.includes('资料不足')&&t.includes('无评级')));
  assert.ok(insufficientTexts.some(t=>t.includes('资料不足1项')));
  assert.ok((await page.locator('.poster-preview h2').innerText()).includes('演示样例'));
  const insufficientEvent=page.waitForEvent('download');await page.getByRole('link',{name:'保存 PNG 图片 ↓'}).click();
  const insufficientDownload=await insufficientEvent;assert.equal(await insufficientDownload.failure(),null);
  const insufficientFile=path.join(out,'explicit-demo-insufficient.png');await insufficientDownload.saveAs(insufficientFile);
  const insufficientBytes=await fs.readFile(insufficientFile);assert.equal(insufficientBytes.readUInt32BE(16),1080);assert.equal(insufficientBytes.readUInt32BE(20),1440);
  await fs.writeFile(path.join(out,'explicit-demo-insufficient-text.json'),JSON.stringify({is_demo:true,real_city_coverage:false,text:insufficientTexts},null,2));
  await page.getByRole('button',{name:'关闭图片预览',exact:true}).click();result.checks.push('insufficient_data_png_explicit_unrated_and_demo_watermark');
  await page.getByRole('button',{name:'打开清明档案',exact:true}).click();
  await page.route('**/cities/demo/tributes',r=>r.request().method()==='POST'?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{code:'storage_failed',message:'测试存储失败：纪念未保存'}})}):r.continue());
  await page.getByRole('button',{name:'点一盏灯',exact:true}).click();await page.getByRole('alert').filter({hasText:'测试存储失败'}).waitFor();assert.equal(await page.getByRole('button',{name:'已点亮',exact:true}).count(),0);
  await page.unroute('**/cities/demo/tributes');await page.getByRole('button',{name:'关闭清明档案',exact:true}).click();result.checks.push('tribute_storage_failure_never_claims_success');
  const fixture=await fs.readFile(path.join(root,'qa','all-alive-demo.json'),'utf8');
  await page.route('**/cities/demo/report',r=>r.fulfill({status:200,contentType:'application/json',body:fixture}));
  await page.getByRole('button',{name:'进入独立样例'}).click();await page.getByText('这份名单，暂时没有讣告。',{exact:true}).waitFor();
  await page.getByRole('button',{name:/生成家乡守候卡/}).click();await page.getByRole('dialog',{name:'图片预览',exact:true}).waitFor();
  assert.ok((await page.locator('.poster-preview h2').innerText()).includes('演示样例'));
  const demoDownload=page.waitForEvent('download');await page.getByRole('link',{name:'保存 PNG 图片 ↓'}).click();await (await demoDownload).saveAs(path.join(out,'explicit-demo-guardian.png'));
  await page.getByRole('button',{name:'关闭图片预览',exact:true}).click();await page.unroute('**/cities/demo/report');result.checks.push('zero_departed_uses_guardian_card_with_explicit_demo_watermark');
  launchCmd('关闭作品.cmd');await choose(page,beijing);await page.getByRole('alert').filter({hasText:'本机服务未启动、已关闭'}).waitFor();
  result.checks.push('beijing_stopped_service_error_regression');
  result.launcher_restart_stdout=launchCmd('启动作品.cmd');assert.equal(await baseFromState(),base);
  await page.getByRole('button',{name:'重新尝试'}).click();await loaded(page,beijing.report);result.checks.push('actual_start_cmd_restart_retry_recovers');
  await page.reload({waitUntil:'networkidle'});await page.getByRole('button',{name:'查我的家乡'}).click();await choose(page,beijing);await loaded(page,beijing.report);
  await page.getByRole('button',{name:'打开立春档案',exact:true}).click();assert.ok(await page.getByRole('button',{name:'已点亮',exact:true}).isDisabled());assert.ok(await page.getByRole('button',{name:'已献花',exact:true}).isDisabled());await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();result.checks.push('refresh_and_launcher_restart_preserve_actions');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'narrow-roster.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const selects=page.getByRole('combobox',{name:/城市|家乡/});
  if(await selects.count()){await selects.first().selectOption('urumqi');await page.getByText('乌鲁木齐',{exact:false}).first().waitFor();result.checks.push('narrow_city_selector');}
  await page.setViewportSize({width:1440,height:1000});
  await onlineContext.storageState({path:path.join(temp,'browser-state.json')});
  launchCmd('关闭作品.cmd');result.checks.push('actual_close_cmd_stops_only_owned_test_instance');
  if(owned)assert.ok(blocker.listening);
  const log=fsSync.openSync(path.join(temp,'offline.log'),'a');
  offline=spawn(python,['-X','utf8',path.join(root,'qa','offline_server.py')],{cwd:root,env,windowsHide:true,stdio:['ignore',log,log]});
  fsSync.closeSync(log);const offlineBase=await baseFromState();assert.equal(offlineBase,base);
  const offlineContext=await newContext(path.join(temp,'browser-state.json'));const offlinePage=await offlineContext.newPage();offlinePage.on('pageerror',e=>result.errors.push(e.message));
  await offlinePage.goto(offlineBase,{waitUntil:'networkidle'});await offlinePage.getByRole('button',{name:'查我的家乡'}).click();await installCanvasAudit(offlinePage);
  for(const city of cities)result.cities.push(await checkCity(offlinePage,offlineContext,offlineBase,city,'offline'));
  result.checks.push('cold_start_with_python_outbound_sockets_denied','all_completed_cities_offline_roster_chart_tribute_png','all_completed_cities_new_light_and_flower_writes_offline');
  await offlineContext.storageState({path:path.join(temp,'offline-browser-state.json')});
  await offlineContext.close();run(['--stop']);
  // Restart another network-denied Python process and a fresh browser context.
  const restartLog=fsSync.openSync(path.join(temp,'offline-restart.log'),'a');
  offline=spawn(python,['-X','utf8',path.join(root,'qa','offline_server.py')],{cwd:root,env,windowsHide:true,stdio:['ignore',restartLog,restartLog]});
  fsSync.closeSync(restartLog);assert.equal(await baseFromState(),base);
  const restored=await newContext(path.join(temp,'offline-browser-state.json'));
  const restoredPage=await restored.newPage();restoredPage.on('pageerror',e=>result.errors.push(e.message));
  await restoredPage.goto(base,{waitUntil:'networkidle'});await restoredPage.getByRole('button',{name:'查我的家乡'}).click();
  result.offline_write_restart=[];
  for(const city of cities){
    await choose(restoredPage,city);await loaded(restoredPage,city.report);
    await restoredPage.getByRole('button',{name:'打开雨水档案',exact:true}).click();
    for(const label of ['已点亮','已献花']){const done=restoredPage.getByRole('button',{name:label,exact:true});await done.waitFor();assert.ok(await done.isDisabled());}
    const exp=await restoredPage.evaluate(()=>localStorage.getItem('jieqi-memorial-experience-v1'));
    const endpoint=`${base}/api/v1/cities/${city.id}/tributes`;
    const saved=await restored.request.get(`${endpoint}?experience_id=${exp}`).then(r=>r.json());
    assert.equal(saved.total,4);assert.deepEqual(saved.terms.lichun,{light:1,flower:1});assert.deepEqual(saved.terms.yushui,{light:1,flower:1});assert.equal(saved.recorded.length,4);
    for(const action of ['light','flower']){
      const retry=await restored.request.post(endpoint,{data:{experience_id:exp,term_id:'yushui',action,idempotency_key:`qa-offline-${city.id}-${action}-${runId}`}});
      assert.equal(retry.status(),200);const body=await retry.json();assert.equal(body.total,4);assert.equal(body.recorded_now,false);
    }
    result.offline_write_restart.push({id:city.id,name:city.name,report_id:city.report.report_id,generated_at:city.report.generated_at,new_term:'yushui',light:1,flower:1,total_after_restart:4,persisted:true,retry_deduplicated:true});
    await restoredPage.getByRole('button',{name:'关闭雨水档案',exact:true}).click();
  }
  result.checks.push('offline_new_writes_persist_after_second_cold_start_and_retries');
  await restored.close();run(['--stop']);
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external_requests,[]);
  result.passed=true;
}catch(error){result.passed=false;result.failure={message:error.message,stack:error.stack};process.exitCode=1;}
finally{
  try{run(['--stop'])}catch{}
  if(onlineContext)await onlineContext.close();if(browser)await browser.close();
  if(blocker?.listening)await new Promise(resolve=>blocker.close(resolve));
  await fs.writeFile(path.join(out,'browser-results.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({passed:result.passed,coverage:result.actual_real_coverage,checks:result.checks,failure:result.failure},null,2));
}
