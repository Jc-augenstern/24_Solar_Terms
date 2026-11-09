// Targeted audit of chart disposal and same-city report version refresh.
// Uses the real local backend with an isolated database; never writes tributes.
import {chromium} from '../node_modules/playwright/index.mjs';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const runId=new Date().toISOString().replace(/[:.]/g,'-');
const out=path.join(root,'qa','frontend-lifecycle');
const temp=path.join(out,'runs',runId);
await fs.mkdir(temp,{recursive:true});
const env={...process.env,DEMO_STATE_DIR:path.join(temp,'runtime'),DEMO_DB_PATH:path.join(temp,'tributes.sqlite3')};
const python=path.join(root,'.venv','Scripts','python.exe');
const run=args=>execFileSync(python,['-X','utf8',path.join(root,'run.py'),...args],{cwd:root,env,encoding:'utf8',windowsHide:true,timeout:30000});
const result={checked_at:new Date().toISOString(),checks:[],cycles:[],errors:[],external_requests:[],test_database:env.DEMO_DB_PATH};
let browser;
try{
  run(['--background','--no-browser','--port','8875']);
  const state=JSON.parse(await fs.readFile(path.join(env.DEMO_STATE_DIR,'server.json'),'utf8'));
  const base=`http://127.0.0.1:${state.port}`;
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='127.0.0.1'||url.hostname==='localhost')return route.continue();
    result.external_requests.push(url.href);return route.abort();
  });
  const page=await context.newPage();page.on('pageerror',e=>result.errors.push(e.message));
  await page.addInitScript(()=>{
    window.qaLifecycle={observers:new Set(),chartListeners:[],reportRequests:[]};
    const NativeResizeObserver=window.ResizeObserver;
    window.ResizeObserver=class extends NativeResizeObserver{
      constructor(callback){super(callback);this.qaTargets=new Set()}
      observe(target,options){this.qaTargets.add(target);window.qaLifecycle.observers.add(this);return super.observe(target,options)}
      unobserve(target){this.qaTargets.delete(target);if(!this.qaTargets.size)window.qaLifecycle.observers.delete(this);return super.unobserve(target)}
      disconnect(){this.qaTargets.clear();window.qaLifecycle.observers.delete(this);return super.disconnect()}
    };
    const add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener=function(type,callback,options){
      if(this instanceof Element&&this.closest('.chart'))window.qaLifecycle.chartListeners.push({target:this,type,callback,capture:typeof options==='boolean'?options:!!options?.capture,active:true});
      return add.call(this,type,callback,options);
    };
    EventTarget.prototype.removeEventListener=function(type,callback,options){
      const capture=typeof options==='boolean'?options:!!options?.capture;
      for(const item of window.qaLifecycle.chartListeners)if(item.target===this&&item.type===type&&item.callback===callback&&item.capture===capture)item.active=false;
      return remove.call(this,type,callback,options);
    };
    const fetchOriginal=window.fetch;
    window.fetch=function(input,init){if(String(input).endsWith('/report'))window.qaLifecycle.reportRequests.push({url:String(input),cache:init?.cache});return fetchOriginal.call(this,input,init)};
  });
  await page.goto(base);await page.getByRole('button',{name:'查我的家乡'}).click();
  const registry=await context.request.get(base+'/api/v1/cities').then(r=>r.json());
  const cities=registry.cities.filter(c=>c.data_status==='ready');assert.ok(cities.length>=2);
  const lifecycle=()=>page.evaluate(()=>({activeObservers:window.qaLifecycle.observers.size,activeChartListeners:window.qaLifecycle.chartListeners.filter(x=>x.active).length,chartElements:document.querySelectorAll('.chart').length}));
  for(let index=0;index<24;index++){
    const city=cities[index%cities.length],start=performance.now();
    await page.getByRole('button',{name:`选择${city.name}`,exact:true}).click();
    await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
    await page.locator('.chart svg').waitFor();
    const chart=await page.locator('.chart').elementHandle();
    const initialId=await chart.getAttribute('_echarts_instance_');assert.ok(initialId);
    const active=await lifecycle();assert.equal(active.activeObservers,1);assert.ok(active.activeChartListeners>0);assert.equal(active.chartElements,1);
    for(const metric of ['precipitation','diurnal_range']){
      await page.getByRole('combobox',{name:'年度曲线指标'}).selectOption(metric);
      await page.locator('.chart svg').waitFor();
      assert.equal((await lifecycle()).activeObservers,1);
    }
    await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
    assert.equal(await chart.getAttribute('_echarts_instance_'),'');
    const released=await lifecycle();assert.deepEqual(released,{activeObservers:0,activeChartListeners:0,chartElements:0});
    await chart.dispose();
    result.cycles.push({index:index+1,city_id:city.id,elapsed_ms:Math.round(performance.now()-start),...released});
  }
  const median=values=>[...values].sort((a,b)=>a-b)[Math.floor(values.length/2)];
  const first=median(result.cycles.slice(3,9).map(c=>c.elapsed_ms)),last=median(result.cycles.slice(-6).map(c=>c.elapsed_ms));
  result.performance={early_median_ms:first,late_median_ms:last,ratio:last/first,scope:'24 repeated real-city switches and chart opens; three metrics per open. Browser automation timing, not a production performance benchmark.'};
  assert.ok(last<Math.max(first*2,first+500),'Repeated chart switching shows a material slowdown requiring investigation');
  result.checks.push('72_chart_instances_across_24_real_city_cycles_release_observers_and_chart_event_handlers','no_material_slowdown_in_24_cycle_check');
  const fixture=JSON.parse(await fs.readFile(path.join(root,'data/reports/demo.json'),'utf8'));
  let version=0;
  await page.route('**/api/v1/cities/demo/report',route=>{
    version++;const report=structuredClone(fixture);
    report.report_id=`demo-cache-fixture-${version}`;report.generated_at=`2026-10-29T13:10:0${version}+00:00`;
    report.summary=`${fixture.summary} [独立样例版本缓存检查 ${version}]`;
    return route.fulfill({contentType:'application/json',body:JSON.stringify(report)});
  });
  for(let iteration=1;iteration<=2;iteration++){
    await page.getByRole('button',{name:'进入独立样例'}).click();
    await page.locator('.report-summary').filter({hasText:`独立样例版本缓存检查 ${iteration}`}).waitFor();
    await page.getByRole('button',{name:'打开立春档案',exact:true}).click();
    assert.ok((await page.locator('.evidence-source').innerText()).includes(`demo-cache-fixture-${iteration}`));
    await page.getByRole('button',{name:'关闭立春档案',exact:true}).click();
  }
  assert.equal(version,2);
  const cacheRequests=await page.evaluate(()=>window.qaLifecycle.reportRequests.filter(r=>r.url.endsWith('/demo/report')));
  assert.equal(cacheRequests.length,2);assert.ok(cacheRequests.every(r=>r.cache==='no-store'));
  result.report_version_check={mode:'explicit demo fixture only',requests:cacheRequests,displayed_version:2};
  result.checks.push('same_city_reselection_fetches_new_report_version_without_app_or_browser_cache');
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external_requests,[]);result.passed=true;
}catch(error){result.passed=false;result.failure={message:error.message,stack:error.stack};process.exitCode=1}
finally{
  if(browser)await browser.close();try{run(['--stop'])}catch{}
  await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({passed:result.passed,checks:result.checks,performance:result.performance,failure:result.failure}));
}
