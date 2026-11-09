import type { Report } from './types';

// Validate the rendering contract, never calculate or replace climate ratings.
export function parseReport(input:unknown,cityId:string):Report {
  type Obj=Record<string,unknown>;
  const object=(v:unknown,p:string):Obj=>{if(!v||typeof v!=='object'||Array.isArray(v))throw new Error(p);return v as Obj};
  const strings=(v:Obj,keys:string[],p:string)=>keys.forEach(k=>{if(typeof v[k]!=='string')throw new Error(`${p}.${k}`)});
  const numeric=(v:unknown,p:string,nullable=false)=>{if(nullable&&v===null)return;if(typeof v!=='number'||!Number.isFinite(v))throw new Error(p)};
  const bool=(v:unknown,p:string)=>{if(typeof v!=='boolean')throw new Error(p)};
  const array=(v:unknown,p:string)=>{if(!Array.isArray(v))throw new Error(p);return v as unknown[]};
  const nullableString=(v:unknown,p:string)=>{if(v!==null&&typeof v!=='string')throw new Error(p)};
  const r=object(input,'report');
  strings(r,['schema_version','report_id','data_status','method_version','generated_at','summary','review_status'],'report');
  bool(r.is_demo,'is_demo');
  const city=object(r.city,'city');strings(city,['id','name'],'city');
  if(city.id!==cityId||r.is_demo!==(cityId==='demo'))throw new Error('城市标识或真实/样例模式不一致');
  const point=object(city.representative_point,'city.representative_point');strings(point,['description'],'city.representative_point');
  numeric(point.latitude,'point.latitude',true);numeric(point.longitude,'point.longitude',true);
  if(city.grid!==null){const grid=object(city.grid,'city.grid');numeric(grid.latitude,'grid.latitude',true);numeric(grid.longitude,'grid.longitude',true)}
  const source=object(r.source,'source');strings(source,['name','url','model','attribution','description'],'source');
  for(const k of ['baseline','recent']){const period=object(r[k],k);numeric(period.start,`${k}.start`);numeric(period.end,`${k}.end`)}
  object(r.quality,'quality');
  const terms=array(r.terms,'terms');if(terms.length!==24)throw new Error('需要完整24节气');
  const ids=new Set<string>();
  for(const [index,value] of terms.entries()){
    const p=`terms[${index}]`,term=object(value,p);
    strings(term,['id','name','season','status','score_display','summary','historical_portrait'],p);
    if(ids.has(term.id as string))throw new Error(`${p}.id重复`);ids.add(term.id as string);
    if(!['春','夏','秋','冬'].includes(term.season as string)||!['alive','critical','departed','insufficient_data'].includes(term.status as string))throw new Error(`${p}.状态或季节`);
    numeric(term.order,`${p}.order`);numeric(term.score,`${p}.score`,term.status==='insufficient_data');nullableString(term.reason,`${p}.reason`);
    const culture=object(term.culture,`${p}.culture`);strings(culture,['text','source_name','source_url'],`${p}.culture`);
    const sensitivity=object(term.sensitivity,`${p}.sensitivity`);bool(sensitivity.sensitive,`${p}.sensitivity.sensitive`);array(sensitivity.changes,`${p}.sensitivity.changes`);
    const metrics=array(term.metrics,`${p}.metrics`),keys=new Set();
    if(metrics.length!==3)throw new Error(`${p}.metrics需3项`);
    for(const value of metrics){const m=object(value,`${p}.metrics`);strings(m,['key','name','unit'],`${p}.metrics`);keys.add(m.key);
      for(const k of ['baseline','recent','delta','baseline_std'])numeric(m[k],`${p}.metrics.${k}`,true);
      for(const k of ['scale','weight','baseline_n','recent_n'])numeric(m[k],`${p}.metrics.${k}`);
    }
    if(!['temperature','precipitation','diurnal_range'].every(k=>keys.has(k)))throw new Error(`${p}.metrics指标不完整`);
    const annual=array(term.annual,`${p}.annual`);if(!annual.length)throw new Error(`${p}.annual为空`);
    for(const value of annual){const a=object(value,`${p}.annual`);strings(a,['start','end'],`${p}.annual`);numeric(a.year,`${p}.annual.year`);bool(a.valid,`${p}.annual.valid`);nullableString(a.reason,`${p}.annual.reason`);for(const k of ['temperature','precipitation','diurnal_range'])numeric(a[k],`${p}.annual.${k}`,!a.valid)}
  }
  return input as Report;
}
