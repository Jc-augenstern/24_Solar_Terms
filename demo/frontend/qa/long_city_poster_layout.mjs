// Layout-only fixtures. Production makePoster, synthetic reports, no real-city publication.
// Optional CLI names: node frontend/qa/long_city_poster_layout.mjs 乌鲁木齐 呼和浩特
import {chromium} from '../node_modules/playwright/index.mjs';
import {build} from '../node_modules/esbuild/lib/main.js';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.join(root,'qa','long-city-poster-fixtures');
await fs.mkdir(out,{recursive:true});
const names=process.argv.slice(2).length?process.argv.slice(2):['乌鲁木齐','呼和浩特'];
const filenameIds={'乌鲁木齐':'urumqi','呼和浩特':'hohhot'};
const productionFile=path.join(root,'frontend','src','poster.ts');
const bundled=await build({entryPoints:[productionFile],bundle:true,write:false,platform:'browser',format:'esm',target:'es2022'});
const sourceHash=crypto.createHash('sha256').update(await fs.readFile(productionFile)).digest('hex');
const fixtures={obituary:JSON.parse(await fs.readFile(path.join(root,'data','reports','demo.json'),'utf8')),guardian:JSON.parse(await fs.readFile(path.join(root,'qa','all-alive-demo.json'),'utf8'))};
const server=http.createServer((req,res)=>{
  if(req.url==='/poster.mjs'){res.setHeader('Content-Type','text/javascript; charset=utf-8');res.end(bundled.outputFiles[0].text)}
  else{res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<!doctype html><meta charset="utf-8"><title>长城市名排版测试：仅演示样例</title><body></body>')}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const result={checked_at:new Date().toISOString(),scope:'Only title and footer layout fixtures using synthetic demo data. City names are test strings; these PNGs are not genuine reports and do not count toward 34-city coverage.',production_source:'frontend/src/poster.ts',production_source_sha256:sourceHash,fixtures:[],errors:[],external_requests:[]};
try{
  const page=await browser.newPage({viewport:{width:1080,height:1440}});
  page.on('pageerror',e=>result.errors.push(e.message));
  await page.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===base||url.protocol==='data:')return route.continue();result.external_requests.push(url.href);return route.abort()});
  await page.goto(base);
  const previews=[];
  for(const name of names)for(const [mode,fixture] of Object.entries(fixtures)){
    assert.equal(fixture.is_demo,true);assert.equal(fixture.city.id,'demo');
    const report=structuredClone(fixture);report.city.name=name;
    report.report_id=`qa-layout-only-demo-${mode}`;
    report.summary=`演示样例，非真实气候结论。城市名称仅用于四字标题排版检查，以下节气状态来自独立合成样例，不代表${name}。`;
    const rendered=await page.evaluate(async report=>{
      const {makePoster}=await import('/poster.mjs');
      const drawn=[],original=CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...args){
        const metrics=this.measureText(String(text));
        drawn.push({text:String(text),font:this.font,x,y,left:x-metrics.actualBoundingBoxLeft,right:x+metrics.actualBoundingBoxRight,top:y-metrics.actualBoundingBoxAscent,bottom:y+metrics.actualBoundingBoxDescent});
        return original.call(this,text,x,y,...args);
      };
      try{
        const blob=await makePoster(report),bitmap=await createImageBitmap(blob);
        const size={width:bitmap.width,height:bitmap.height};bitmap.close();
        const dataUrl=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(blob)});
        return {...size,dataUrl,drawn};
      }finally{CanvasRenderingContext2D.prototype.fillText=original}
    },report);
    assert.equal(rendered.width,1080);assert.equal(rendered.height,1440);
    const texts=rendered.drawn.map(item=>item.text);
    const expectedTitle=`${name} · ${mode==='guardian'?'家乡守候卡':'城市讣告'}`;
    const title=rendered.drawn.find(item=>item.text===expectedTitle);assert.ok(title);
    const banner=rendered.drawn.find(item=>item.text==='演示样例，非真实气候结论');assert.ok(banner&&banner.y===291);
    for(const term of report.terms)assert.ok(texts.some(t=>t.includes(`${String(term.order).padStart(2,'0')}  ${term.name}`)));
    const footer=rendered.drawn.find(item=>item.y===1378);assert.ok(footer.text.startsWith(name)&&footer.text.includes('24节气'));
    for(const item of rendered.drawn)assert.ok(item.left>=40&&item.right<=1040&&item.top>=40&&item.bottom<=1400,`Text overflow: ${item.text}`);
    const filename=`DEMO-layout-only-${filenameIds[name]||names.indexOf(name)}-${mode}.png`;
    const bytes=Buffer.from(rendered.dataUrl.split(',')[1],'base64');
    assert.equal(bytes.readUInt32BE(16),1080);assert.equal(bytes.readUInt32BE(20),1440);
    await fs.writeFile(path.join(out,filename),bytes);
    previews.push({name,mode,dataUrl:rendered.dataUrl});
    result.fixtures.push({city_name_test_string:name,mode,is_demo:true,counts_toward_real_coverage:false,file:filename,width:1080,height:1440,unique_terms:report.terms.length,title,footer,watermark:banner.text,all_text_inside_border:true});
  }
  await page.evaluate(previews=>{
    document.body.style.cssText='margin:0;display:grid;grid-template-columns:540px 540px;background:#eee';
    for(const preview of previews){const img=document.createElement('img');img.src=preview.dataUrl;img.style.cssText='width:540px;height:720px;display:block';img.alt=`${preview.name} ${preview.mode} 演示排版`;document.body.append(img)}
  },previews);
  await page.screenshot({path:path.join(out,'DEMO-layout-only-contact-sheet.png'),fullPage:true});
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external_requests,[]);result.passed=true;
}catch(error){result.passed=false;result.failure={message:error.message,stack:error.stack};process.exitCode=1}
finally{
  await browser.close();await new Promise(resolve=>server.close(resolve));
  await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({passed:result.passed,fixtures:result.fixtures.length,failure:result.failure}));
}
