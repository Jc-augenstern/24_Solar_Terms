# 本机作品共享契约 v1（34城扩展）

目录：frontend/ React TS Vite；backend/ FastAPI；scripts/ Python数据；config/cities.json 唯一城市注册表；data/reports/{city_id}.json（仅已校验发布城市）及独立demo.json；data/methodology/v0.1.json；data/raw/ 缓存；data/tributes.sqlite3。

GET /api/v1/cities -> {cities:[{id,city_id,name,region,category,aliases,representative_point,time_window,report_id,data_status,reason,update_status,update_reason,last_success_report}], demo:{id:'demo',name:'样例城',data_status:'demo',reason:'演示样例，非真实气候结论'}}。城市恰好34个，稳定ID见config/cities.json，旧六城ID不变。分类为直辖市4、大陆省会22、自治区首府5、港澳台代表城市3。data_status: ready / preparing / acquisition_blocked / not_connected / report_missing / invalid_report；样例 demo。ready从实际报告校验生成；若更新失败但旧报告仍有效，保持ready并在reason/update_reason说明。

代表点 source 保存GeoNames原记录、URL、核对时间及原响应路径，crs为WGS84。time_window统一北京时间UTC+08:00及1961—1990/1996—2025。数据报告的source.requests_manifest指向对应城市原始清单，旧北京保留raw/beijing/request_manifest.json，新版可使用raw/{city_id}/manifests/{hash}.json不可变清单。

GET /api/v1/cities/{id}/report -> Report（原始报告不混入计数）。未接入503 not_connected、准备503 preparing、获取受阻503 acquisition_blocked、缺失404 report_missing、JSON损坏500 report_parse_failed、字段/评级不兼容500 report_schema_mismatch、读取失败500 report_unreadable、未知城市404 unknown_city。错误JSON {detail:{code,message}}。城市列表中三种已安装报告读取/结构错误统一为data_status: invalid_report，reason保留具体原因。不以样例或另一城数据兜底。
GET /api/v1/cities/{id}/tributes?experience_id=UUID -> {total,light,flower,terms:{[term_id]:{light,flower}}, recorded:[{term_id,action}]}。
POST /api/v1/cities/{id}/tributes body {experience_id,term_id,action:'light'|'flower',idempotency_key} -> 同计数对象加 recorded_now:boolean。双唯一约束：城市/模式/体验/节气/动作，以及幂等键；冲突参数409。SQLite写入成功才返回成功。
GET /api/v1/methodology/v0.1 -> 方法JSON；GET /api/health -> {ok:true}。

Report:
```
{
 schema_version:'1.0', report_id:'...', is_demo:boolean,
 city:{id,name,representative_point:{latitude,longitude,description},grid:{latitude,longitude,elevation}},
 data_status:'ready'|'demo', baseline:{start:1961,end:1990}, recent:{start:1996,end:2025},
 source:{name,url,model,attribution,description}, method_version:'v0.1', generated_at:'ISO',
 summary:'数据模板摘要', review_status:'待团队人工审阅',
 quality:{...}, terms:[Term共24个]
}
Term:
```
{id:'lichun',name:'立春',season:'春',order:1,status:'alive'|'critical'|'departed'|'insufficient_data',
 score:number|null,score_display:string,reason:string|null,summary:string,
 culture:{text:string,source_name:string,source_url:string},historical_portrait:string,
 metrics:[{key:'temperature'|'precipitation'|'diurnal_range',name,unit,baseline:number|null,recent:number|null,delta:number|null,baseline_std:number|null,scale:number,weight:number,baseline_n:number,recent_n:number}],
 annual:[{year,start,end,valid:boolean,reason:string|null,temperature:number|null,precipitation:number|null,diurnal_range:number|null}],
 sensitivity:{sensitive:boolean,changes:[]}}
```
以上是形状说明，非JSON文件。season 按立春起春夏秋冬各6项，小寒大寒属于冬；年度按交节公历年归档。score_display由数据层给出（两位小数；若四舍五入跨档用 <40 / <70），前端不计算评级。状态计数允许从terms归纳。样例城市名固定为样例城，与真实城市分离；始终显示“演示样例，非真实气候结论”。

样例与真实使用同一结构。无已故输出“家乡守候卡”，有已故输出“城市讣告”。纪念 experience_id 使用 localStorage 持久化，刷新/重新打开不重建，显式开始新体验才生成新标识。资料不足仍可查看与纪念，但不生成确定评级。

所有报告正文、摘要、曲线、海报同源。运行时无外网依赖。采用本机已安装中文字体可满足本机 Demo，画布需 await document.fonts.ready；不可分发Windows字体文件。
