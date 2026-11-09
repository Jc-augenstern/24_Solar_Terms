import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkAreaComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { api, getReport, experience, newExperience, requestKey } from './api';
import { ART_NOTE, DEMO_NOTE, labels, number, periods, type City, type Report, type Term, type Status, type MetricKey, type Action, type Tributes } from './types';
import { makePoster } from './poster';

echarts.use([LineChart, GridComponent, TooltipComponent, MarkAreaComponent, AriaComponent, SVGRenderer]);
const states:Status[]=['alive','critical','departed','insufficient_data'];
const errorText=(e:unknown)=>e instanceof Error?e.message:'操作失败，请重试。';
function StatusTag({status}:{status:Status}) {return <span className={`status status-${status}`}><span aria-hidden="true" className="status-dot"/>{labels[status]}</span>}
function DemoNotice(){return <div className="demo-notice"><span aria-hidden="true">◇</span> {DEMO_NOTE}</div>}
function ErrorNotice({children,retry}:{children:ReactNode;retry?:()=>void}) {return <div className="error-notice" role="alert"><p>{children}</p>{retry&&<button onClick={retry}>重新尝试</button>}</div>}
const cityStatusLabel=(status:string)=>(({ready:'真实报告可用',preparing:'数据准备中',running:'数据准备中',acquisition_blocked:'获取受阻',blocked:'获取受阻',failed:'获取受阻',invalid_report:'报告校验失败',report_missing:'报告文件缺失',not_connected:'尚未完成接入'} as Record<string,string>)[status]||'尚未完成接入');
const cityCategory=(city:City)=>city.category_label||city.category||'城市';
function CityPicker({cities,selected,onChoose,onRefresh}:{cities:City[];selected:City|null;onChoose:(city:City)=>void;onRefresh:()=>void}) {
  const [query,setQuery]=useState('');
  const list=useRef<HTMLElement>(null);
  const filtered=useMemo(()=>{const value=query.trim().toLocaleLowerCase();return cities.filter(city=>[city.name,city.region,city.id,...(city.aliases||[])].some(s=>s?.toLocaleLowerCase().includes(value)))},[cities,query]);
  const groups=useMemo(()=>{const grouped=new Map<string,City[]>();for(const city of filtered){const name=cityCategory(city);grouped.set(name,[...(grouped.get(name)||[]),city])}return [...grouped]},[filtered]);
  useEffect(()=>{
    const box=list.current,button=box?.querySelector<HTMLElement>('[aria-current="true"]');
    if(box&&button){const b=box.getBoundingClientRect(),r=button.getBoundingClientRect();if(r.top<b.top||r.bottom>b.bottom)box.scrollTop+=r.top-b.top-box.clientHeight/2+button.offsetHeight/2}
  },[selected?.id,query]);
  return <div className="city-picker">
    <div className="city-coverage"><span>真实报告 {cities.filter(city=>city.data_status==='ready').length} / {cities.length} 城</span><button className="text-button" onClick={onRefresh}>刷新状态</button></div>
    <label className="city-search-label" htmlFor="city-search">搜索城市或省级地区</label><input id="city-search" type="search" className="city-search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="如：杭州、浙江、乌鲁木齐" autoComplete="off"/>
    {selected&&selected.id!=='demo'&&<p className="current-city">正在查看：<strong>{selected.name}</strong> · {selected.region} <button className="text-button" onClick={()=>{setQuery('');const box=list.current,button=box?.querySelector<HTMLElement>('[aria-current="true"]');if(box&&button){const b=box.getBoundingClientRect(),r=button.getBoundingClientRect();box.scrollTop+=r.top-b.top-box.clientHeight/2+button.offsetHeight/2}}}>定位</button></p>}
    <label className="mobile-city-picker">选择家乡档案<select aria-label="选择家乡城市" value={filtered.some(city=>city.id===selected?.id)?selected?.id||'':''} onChange={e=>{const city=cities.find(city=>city.id===e.target.value);if(city)onChoose(city)}}><option value="" disabled>{filtered.length?'选择城市':'没有匹配城市'}</option>{groups.map(([category,items])=><optgroup label={category} key={category}>{items.map(city=><option value={city.id} key={city.id}>{city.name} · {city.region} · {cityStatusLabel(city.data_status)}</option>)}</optgroup>)}</select></label>
    <nav className="city-list" aria-label="城市选择" ref={list}>{groups.map(([category,items])=><section className="city-group" key={category}><h3>{category} <span>{items.length}</span></h3>{items.map(city=><button className={`city-button ${selected?.id===city.id?'selected':''}`} onClick={()=>onChoose(city)} key={city.id} aria-label={`选择${city.name}`} aria-current={selected?.id===city.id?'true':undefined} title={city.reason||undefined}><span>{city.name}</span><small className="city-region">{city.region}</small><small>{cityStatusLabel(city.data_status)}</small><span className="city-arrow" aria-hidden="true">↗</span></button>)}</section>)}</nav>
    {!filtered.length&&<p className="city-no-results" role="status">没有匹配城市。<button className="text-button" onClick={()=>setQuery('')}>查看全部城市</button></p>}
  </div>;
}

function Modal({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const d=ref.current!;d.showModal();return ()=>d.close()},[]);
  return <dialog ref={ref} className={wide?'modal modal-wide':'modal'} onCancel={e=>{e.preventDefault();onClose()}} onClick={e=>{if(e.target===ref.current)onClose()}} aria-label={title}>
    <div className="modal-top"><span>{title}</span><button className="close-button" onClick={onClose} aria-label={`关闭${title}`}>×</button></div>{children}
  </dialog>;
}

function AnnualChart({term,report}:{term:Term;report:Report}) {
  const [metric,setMetric]=useState<MetricKey>('temperature');
  const ref=useRef<HTMLDivElement>(null);
  const chosen=term.metrics.find(m=>m.key===metric)!;
  useEffect(()=>{
    if(!ref.current||!chosen)return;
    const chart=echarts.init(ref.current,undefined,{renderer:'svg'});
    const years=Array.from({length:report.recent.end-report.baseline.start+1},(_,i)=>report.baseline.start+i);
    const byYear=new Map(term.annual.map(a=>[a.year,a]));
    chart.setOption({animation:false,aria:{enabled:true,description:`${term.name}年度${chosen.name}，${report.is_demo?DEMO_NOTE:report.source.name}`},
      grid:{left:54,right:22,top:32,bottom:38},
      tooltip:{trigger:'axis',renderMode:'richText',valueFormatter:(v:unknown)=>v==null?'无有效值':`${Number(v).toFixed(2)} ${chosen.unit}`},
      xAxis:{type:'category',data:years.map(String),boundaryGap:false,axisLine:{lineStyle:{color:'#a4a99d'}},axisLabel:{color:'#686e63',interval:Math.max(0,Math.floor(years.length/6)-1)}},
      yAxis:{type:'value',name:chosen.unit,scale:true,nameTextStyle:{color:'#686e63'},axisLabel:{color:'#686e63'},splitLine:{lineStyle:{color:'#dedfd6'}}},
      series:[{name:chosen.name,type:'line',connectNulls:false,showSymbol:false,lineStyle:{width:2,color:'#5c6956'},itemStyle:{color:'#5c6956'},data:years.map(year=>{const a=byYear.get(year);return a?.valid?a[metric]:null}),
        markArea:{silent:true,label:{show:false},data:[[{xAxis:String(report.baseline.start),itemStyle:{color:'rgba(130,145,120,.10)'}},{xAxis:String(report.baseline.end)}],[{xAxis:String(report.recent.start),itemStyle:{color:'rgba(178,152,110,.10)'}},{xAxis:String(report.recent.end)}]]}}]});
    const resize=new ResizeObserver(()=>chart.resize());resize.observe(ref.current);
    return ()=>{resize.disconnect();chart.dispose()};
  },[term,report,metric,chosen]);
  return <section className="chart-section"><div className="section-heading"><h3>年度证据</h3><label className="select-label">查看指标 <select value={metric} onChange={e=>setMetric(e.target.value as MetricKey)} aria-label="年度曲线指标">{term.metrics.map(m=><option value={m.key} key={m.key}>{m.name}</option>)}</select></label></div>
    {report.is_demo&&<DemoNotice/>}<div className="chart" ref={ref} role="img" aria-label={`${term.name}${chosen?.name}年度曲线`}/>
    <p className="small muted">浅灰：历史 {report.baseline.start}—{report.baseline.end}　浅暖：近期 {report.recent.start}—{report.recent.end}。缺失或无效年度留空，不补零。</p>
    <details className="annual-details"><summary>查看年度数值与实际节气窗口</summary><div className="table-scroll"><table><caption>{term.name} · {chosen?.name}（{chosen?.unit}）{report.is_demo?` · ${DEMO_NOTE}`:''}</caption><thead><tr><th>年份</th><th>窗口起止</th><th>数值</th><th>有效性</th></tr></thead><tbody>{term.annual.map(a=><tr key={a.year}><td>{a.year}</td><td>{a.start} — {a.end}</td><td>{number(a[metric])}</td><td>{a.valid?'有效':a.reason||'无效'}</td></tr>)}</tbody></table></div></details>
  </section>;
}

function MethodContent({version}:{version:string}) {
  const [data,setData]=useState<unknown>(null),[error,setError]=useState('');
  const load=useCallback(()=>{setError('');api(`/methodology/${version}`).then(setData).catch(e=>setError(errorText(e)))},[version]);
  useEffect(load,[load]);
  return <div className="method-content"><p className="eyebrow">关于这份名册 · {version}</p><h2>纪念旧候，<br/>不是宣告节气消失。</h2><p>{ART_NOTE}</p><p>评级对象是城市代表点在一个节气时段的历史气候画像。“旧候相似指数”是本作品的艺术规则，不是节气存亡概率或科学死亡标准。</p>
    <dl className="method-list"><div><dt>比较什么</dt><dd>历史 1961—1990 年与近期 1996—2025 年。固定 ERA5 再分析数据；不等同于气象站实测，不代表全市每个地点。</dd></div>
    <div><dt>如何划窗</dt><dd>逐年计算交节日期，以北京时间交节日开始，到下一节气前一日结束；采用完整日的近似，保留跨年窗口。</dd></div>
    <div><dt>三个指标</dt><dd>窗口日均温平均值（60%）、日降水量平均值（25%）、日最高温减日最低温的平均值（15%）。</dd></div>
    <div><dt>指数规则</dt><dd>d = |近期均值 − 历史均值| / max(历史样本标准差, 最小尺度)。最小尺度均为 0.5（温度 ℃、降水 mm/日）。D 为三项 d 的加权和，S = 100 / (1 + D)。</dd></div>
    <div><dt>艺术分档</dt><dd>S ≥ 70 健在；40 ≤ S &lt; 70 病危；S &lt; 40 已故。依据未舍入指数分档；临界显示值不会越过分档边界。</dd></div>
    <div><dt>有效数据</dt><dd>任一核心变量有效日少于窗口的 90%，该年度无效；任一比较期有效年度少于 27 年，显示资料不足。缺失不填零。敏感性标记不等于统计置信度。</dd></div></dl>
    {error?<ErrorNotice retry={load}>{error} 方法文件未能载入；以上为本版本固定说明。</ErrorNotice>:!data?<p role="status">读取本地方法文件…</p>:<details><summary>完整方法记录与来源</summary><pre className="json-block">{JSON.stringify(data,null,2)}</pre></details>}
  </div>;
}

export default function App() {
  const [entered,setEntered]=useState(false),[cities,setCities]=useState<City[]>([]),[demo,setDemo]=useState<City|null>(null),[citiesError,setCitiesError]=useState('');
  const [selectedCity,setSelectedCity]=useState<City|null>(null),[report,setReport]=useState<Report|null>(null),[loading,setLoading]=useState(false),[reportError,setReportError]=useState('');
  const [filter,setFilter]=useState<Status|'all'>('all'),[termId,setTermId]=useState<string|null>(null),[method,setMethod]=useState(false);
  const [tributes,setTributes]=useState<Tributes|null>(null),[tributeError,setTributeError]=useState(''),[pending,setPending]=useState<Action|null>(null),[feedback,setFeedback]=useState('');
  const [experienceId,setExperienceId]=useState<string|null>(()=>{try{return experience()}catch{return null}});
  const [poster,setPoster]=useState<{url:string;name:string;cityName:string;isDemo:boolean}|null>(null),[exporting,setExporting]=useState(false),[exportError,setExportError]=useState('');
  const requestNumber=useRef(0), tributeNumber=useRef(0), activeTerm=useRef(termId);
  const reportController=useRef<AbortController|null>(null);
  activeTerm.current=termId;
  const loadCities=useCallback(()=>{setCitiesError('');api<{cities:City[];demo:City}>('/cities').then(data=>{setCities(data.cities);setDemo(data.demo);setSelectedCity(previous=>previous?(previous.id==='demo'?data.demo:data.cities.find(city=>city.id===previous.id)||previous):null)}).catch(e=>setCitiesError(errorText(e)))},[]);
  useEffect(loadCities,[loadCities]);
  const chooseCity=useCallback(async(city:City)=>{
    const current=++requestNumber.current;++tributeNumber.current;
    reportController.current?.abort();const controller=new AbortController();reportController.current=controller;
    setSelectedCity(city);setReport(null);setReportError('');setTermId(null);setFilter('all');setTributes(null);setTributeError('');setFeedback('');setExportError('');setPoster(null);setExporting(false);setPending(null);
    setLoading(true);
    try{const next=await getReport(city.id,city.name,controller.signal);if(current===requestNumber.current)setReport(next)}
    catch(e){if(current===requestNumber.current)setReportError(errorText(e))}
    finally{if(current===requestNumber.current)setLoading(false)}
  },[]);
  useEffect(()=>()=>{++requestNumber.current;++tributeNumber.current;reportController.current?.abort()},[]);
  const loadTributes=useCallback(()=>{
    if(!report||!experienceId)return;
    const current=++tributeNumber.current;
    setTributeError('');api<Tributes>(`/cities/${report.city.id}/tributes?experience_id=${encodeURIComponent(experienceId)}`).then(data=>{if(current===tributeNumber.current)setTributes(data)}).catch(e=>{if(current===tributeNumber.current)setTributeError(errorText(e))});
  },[report,experienceId]);
  useEffect(loadTributes,[loadTributes]);
  useEffect(()=>()=>{if(poster)URL.revokeObjectURL(poster.url)},[poster]);
  const counts=useMemo(()=>Object.fromEntries(states.map(s=>[s,report?.terms.filter(t=>t.status===s).length||0])) as Record<Status,number>,[report]);
  const term=report?.terms.find(t=>t.id===termId);
  const representative=selectedCity?.representative_point||report?.city.representative_point;
  const coordinateSource=representative?.source?.url||representative?.source_url;
  const recorded=(action:Action)=>!!tributes?.recorded.some(r=>r.term_id===termId&&r.action===action);
  async function tribute(action:Action) {
    if(!report||!term||!experienceId||pending)return;
    const generation=requestNumber.current, submittedTerm=term.id;
    ++tributeNumber.current;
    setPending(action);setTributeError('');setFeedback('');
    try {
      const data=await api<Tributes>(`/cities/${report.city.id}/tributes`,{method:'POST',body:JSON.stringify({experience_id:experienceId,term_id:term.id,action,idempotency_key:requestKey(experienceId,report.city.id,term.id,action)})});
      if(generation===requestNumber.current){setTributes(data);if(activeTerm.current===submittedTerm)setFeedback(data.recorded_now===false?'这份心意已记录，本次体验不重复计数。':action==='light'?'灯已点亮。为家乡的下一次节气守候。':'花已留下。这份纪念已保存到本机。')}
    } catch(e){if(generation===requestNumber.current)setTributeError(errorText(e))}finally{if(generation===requestNumber.current)setPending(null)}
  }
  async function generatePoster(){
    if(!report||exporting)return;const generation=requestNumber.current,source=report;
    setExportError('');setExporting(true);
    try{const blob=await makePoster(source);if(generation===requestNumber.current)setPoster({url:URL.createObjectURL(blob),name:`${source.city.name}_${source.terms.some(t=>t.status==='departed')?'城市讣告':'家乡守候卡'}${source.is_demo?'_演示样例':''}.png`,cityName:source.city.name,isDemo:source.is_demo})}
    catch(e){if(generation===requestNumber.current)setExportError(`图片导出失败：${errorText(e)}`)}
    finally{if(generation===requestNumber.current)setExporting(false)}
  }
  function beginNewExperience(){try{const id=newExperience();++tributeNumber.current;setTributes(null);setExperienceId(id);setFeedback('已开始新的体验；本机历史纪念记录继续保留。')}catch{setTributeError('浏览器无法保存体验标识，未开始新体验。请允许本地存储。')}}
  function enter(){setEntered(true);window.scrollTo({top:0,behavior:'instant'})}
  return <>
    <header className="site-header"><button className="brand" onClick={()=>{setEntered(false);setTermId(null)}} aria-label="返回作品入口"><span className="brand-mark" aria-hidden="true">候</span><span>节气讣告<small>家乡旧候纪念馆</small></span></button><div className="header-right"><span className="local-label"><i/>本地档案 · 34 城</span><button className="text-button" onClick={()=>setMethod(true)}>方法与来源 ↗</button></div></header>
    {!entered?<main className="landing"><div className="landing-main"><div className="landing-copy"><p className="eyebrow">二十四节气 / 地方气候档案</p><h1>查查你家乡，<br/>死了几个<span className="outline-word">节气。</span></h1><div className="landing-rule"/><p className="core-line">日历上的节气依然准时。<br/>我们纪念的，是家乡正在改变的季节模样。</p><p className="landing-intro">翻开家乡的节气名册，阅读过去与现在的气候证据。<br className="desktop-break"/>为仍在守候的季节，留一盏灯。</p><button className="primary enter-button" onClick={enter}>查我的家乡 <span aria-hidden="true">↗</span></button></div><div className="season-art" aria-hidden="true"><div className="orbit outer"/><div className="orbit middle"/><div className="orbit inner"/><span className="orbit-axis vertical"/><span className="orbit-axis horizontal"/><span className="art-word">旧<br/>候</span><span className="art-north">冬至</span><span className="art-east">春分</span><span className="art-south">夏至</span><span className="art-west">秋分</span><div className="art-note">一岁 · 二十四候<br/>时间照常向前</div></div></div><div className="landing-footer"><span>01 / 进入纪念馆</span><p>{ART_NOTE}</p><span>本机运行 · 离线可读</span></div></main>:
    <main className="museum"><aside className="city-sidebar"><p className="eyebrow">01 / 选择家乡</p><h2>从一个地方，<br/>重新读懂四季。</h2><p className="muted small">每座城市对应固定代表点。<br/>已准备的报告可离线阅读。</p>{citiesError?<ErrorNotice retry={loadCities}>{citiesError}</ErrorNotice>:<CityPicker cities={cities} selected={selectedCity} onChoose={chooseCity} onRefresh={loadCities}/>}
      <div className="sample-entry"><span className="eyebrow">开发与交互验证</span><button className={`sample-button ${selectedCity?.id==='demo'?'selected':''}`} onClick={()=>demo&&chooseCity(demo)} disabled={!demo}>进入独立样例 <span aria-hidden="true">→</span></button><p className="small muted">样例城为虚构数据，不计入真实城市覆盖。</p></div><button className="text-button" onClick={()=>setMethod(true)}>阅读评级方法 ↗</button></aside>
      <div className="archive-content">{!selectedCity?<section className="empty-welcome"><p className="eyebrow">地方档案 / 等待翻阅</p><div className="big-number">24</div><h2>名字仍在日历上。<br/>季节的模样，留在证据里。</h2><p>选择左侧家乡查看接入状态，<br/>或进入独立样例，体验完整纪念流程。</p><p className="art-note-text">{ART_NOTE}</p></section>:loading?<section className="loading-state" role="status"><span className="loading-dot"/>正在翻开{selectedCity.name}的档案…</section>:reportError?<section className="unavailable-state"><p className="eyebrow">{selectedCity.name} / 档案状态</p><h2>{['not_connected','preparing','acquisition_blocked'].includes(selectedCity.data_status)?cityStatusLabel(selectedCity.data_status):'报告暂时无法打开'}</h2><ErrorNotice retry={()=>chooseCity(selectedCity)}>{reportError}</ErrorNotice><p className="muted">报告准备状态表示获取、计算或校验进度；“资料不足”仅用于真实数据计算后未达到质量要求的节气。</p>{demo&&<button onClick={()=>chooseCity(demo)} className="secondary">体验独立样例 →</button>}</section>:report&&<>
        {report.is_demo&&<DemoNotice/>}<div className="archive-heading"><div><p className="eyebrow">02 / 城市名册 · {report.is_demo?'独立样例':'ERA5 真实再分析'}</p><h1>{report.city.name}<span>旧候名册</span></h1><p className="period-label">历史 {report.baseline.start}—{report.baseline.end}<span> → </span>近期 {report.recent.start}—{report.recent.end}</p></div><button className="primary poster-button" onClick={generatePoster} disabled={exporting}>{exporting?'正在生成图片…':`生成${counts.departed?'城市讣告':'家乡守候卡'}`} <span aria-hidden="true">↗</span></button></div>
        {!report.is_demo&&<p className="city-location">{selectedCity.region||report.city.region} · {cityCategory(selectedCity)}<span>固定代表点 WGS84：{report.city.representative_point.latitude}°N，{report.city.representative_point.longitude}°E</span></p>}
        {selectedCity.update_status&&!['complete','ready','published'].includes(selectedCity.update_status)&&(selectedCity.update_reason||selectedCity.reason)&&<p className="update-status" role="status">{selectedCity.update_status==='preparing'?'数据更新中，当前展示已校验报告。':''}{selectedCity.reason||selectedCity.update_reason}</p>}
        <p className="report-summary">{report.summary}</p><p className="art-note-text">{ART_NOTE}</p>
        {counts.departed===0&&<div className="no-obituary"><span aria-hidden="true">◦</span><p><strong>这份名单，暂时没有讣告。</strong> 我们仍可以为家乡留下观察与守候。</p></div>}
        {exportError&&<ErrorNotice retry={generatePoster}>{exportError}</ErrorNotice>}
        <div className="filter-bar" role="group" aria-label="筛选节气状态"><button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>全部 <b>{report.terms.length}</b></button>{states.map(s=><button key={s} className={filter===s?'active':''} onClick={()=>setFilter(s)}>{labels[s]} <b>{counts[s]}</b></button>)}</div>
        <div className="seasons">{['春','夏','秋','冬'].map((season,index)=>{const terms=report.terms.filter(t=>t.season===season&&(filter==='all'||t.status===filter)).sort((a,b)=>a.order-b.order);return terms.length?<section className="season-section" key={season}><div className="season-heading"><h2>{season}<span>{['SPRING','SUMMER','AUTUMN','WINTER'][index]}</span></h2><span>{String(index+1).padStart(2,'0')} / {terms.length} 份档案</span></div><div className="term-grid">{terms.map(t=><button key={t.id} className={`term-card term-${t.status}`} onClick={()=>{setTermId(t.id);setFeedback('')}} aria-label={`打开${t.name}档案`}><div className="card-top"><span className="term-index">{String(t.order).padStart(2,'0')}</span><StatusTag status={t.status}/></div><div className="term-name-row"><h3>{t.name}</h3><div className="term-score"><strong>{t.score==null?'—':t.score_display}</strong><span>旧候相似指数</span></div></div><p>{t.reason||t.summary}</p><div className="card-bottom"><span>{t.sensitivity?.sensitive?'对参数敏感':'阅读变化证据'}</span><span aria-hidden="true">↗</span></div></button>)}</div></section>:null})}</div>
        {filter!=='all'&&counts[filter]===0&&<div className="filter-empty">本报告没有“{labels[filter]}”节气。<button className="text-button" onClick={()=>setFilter('all')}>查看全部名册</button></div>}
        <footer className="report-footer"><div><p className="eyebrow">为下一次节气留下观察</p><p>记录下一次交节时的天气与生活感受。个人观察可以成为记忆，<br/>但不代替气候统计，也不改变这份艺术评级。</p></div><div className="source-note"><p>{report.source.url?<a className="source-link" href={report.source.url} target="_blank" rel="noreferrer">{report.source.name} ↗</a>:report.source.name} · {report.source.model}</p><p>{report.is_demo?DEMO_NOTE:'城市代表点再分析，不是气象站实测'}</p><p>{report.source.attribution}</p><p>方法 {report.method_version} · {report.review_status}</p><button className="text-button" onClick={()=>setMethod(true)}>查看方法与来源 ↗</button></div></footer>
      </>}</div></main>}
    {term&&report&&<Modal title={`${term.name}档案`} onClose={()=>{setTermId(null);setFeedback('')}} wide><article className="term-detail">{report.is_demo&&<DemoNotice/>}<p className="eyebrow">{report.city.name} / {term.season}季 / 档案 {String(term.order).padStart(2,'0')}</p><div className="detail-heading"><div><h2>{term.name}</h2><p>{term.name}时段的旧候画像</p></div><div className="detail-score"><StatusTag status={term.status}/><strong>{term.score==null?'—':term.score_display}</strong><span>旧候相似指数</span></div></div><p className="detail-summary">{term.reason||term.summary}</p><p className="small muted">{periods(report)} · {report.source.name} · {report.method_version}</p>
      {term.sensitivity?.sensitive&&<p className="sensitivity-note">对参数敏感：单项权重、尺度或分档边界扰动可改变状态。这不是统计置信度。</p>}
      <div className="story-columns"><section><h3>节气的文化含义</h3><p>{term.culture.text}</p><a href={term.culture.source_url} target="_blank" rel="noreferrer" className="source-link">来源：{term.culture.source_name} ↗</a></section><section><h3>{report.is_demo?'样例历史画像':'当地历史画像'}</h3><p>{term.historical_portrait}</p></section></div>
      <section className="comparison-section"><div className="section-heading"><h3>今昔指标对比</h3><button className="text-button" onClick={()=>setMethod(true)}>如何计算 ↗</button></div><div className="metric-grid">{term.metrics.map(m=><div className="metric-card" key={m.key}><h4>{m.name}<small>{m.unit}</small></h4><div className="metric-values"><span><small>{report.baseline.start}—{report.baseline.end}</small>{number(m.baseline)}</span><i aria-hidden="true">→</i><span><small>{report.recent.start}—{report.recent.end}</small>{number(m.recent)}</span></div><p>变化 <strong>{number(m.delta,true)} {m.unit}</strong></p><p className="small muted">有效年度 {m.baseline_n} / {m.recent_n}<br/>历史样本标准差 {number(m.baseline_std)} {m.unit}</p></div>)}</div></section>
      <AnnualChart key={`${report.city.id}:${report.report_id}:${report.generated_at}:${term.id}`} term={term} report={report}/>
      <section className={`tribute-section ${recorded('light')?'illuminated':''}`}><div><p className="eyebrow">留一份心意</p><h3>{term.status==='alive'?'为这一候，继续守候。':'记住家乡的季节模样。'}</h3><p>{tributes?`本机纪念次数：${tributes.total} 次`:'正在读取本机纪念记录…'} <span className="small">{report.is_demo?'（独立样例）':'（当前城市）'}</span></p>{tributes&&<p className="small muted">本档案：点灯 {tributes.terms[term.id]?.light||0} 次 · 献花 {tributes.terms[term.id]?.flower||0} 次</p>}</div><div className="tribute-actions"><button className={recorded('light')?'tribute-done':''} disabled={!!pending||!experienceId||recorded('light')} onClick={()=>tribute('light')}><span aria-hidden="true">♧</span>{pending==='light'?'保存中…':recorded('light')?'已点亮':'点一盏灯'}</button><button className={recorded('flower')?'tribute-done':''} disabled={!!pending||!experienceId||recorded('flower')} onClick={()=>tribute('flower')}><span aria-hidden="true">✳</span>{pending==='flower'?'保存中…':recorded('flower')?'已献花':'献一束花'}</button></div>
      {!experienceId&&<ErrorNotice>无法保存本地体验标识，请允许浏览器本地存储后刷新。纪念操作暂不可用。</ErrorNotice>}{tributeError&&<ErrorNotice retry={loadTributes}>{tributeError} 未确认保存成功；请检查后重试。</ErrorNotice>}{feedback&&<p className="tribute-feedback" role="status">{feedback}</p>}<p className="tribute-footnote small">同一体验、城市、节气和动作只记录一次；刷新不重计。<button className="text-button" onClick={beginNewExperience} disabled={!!pending}>开始新体验</button></p></section>
      <section className="evidence-source"><h3>来源与记录</h3>{!report.is_demo&&selectedCity&&<p>{selectedCity.region} · {cityCategory(selectedCity)}</p>}<p>{report.source.description}</p><p className="small">{report.source.attribution}</p><p className="small">{representative?.description}{report.city.representative_point.latitude!=null?`（${report.city.representative_point.latitude}, ${report.city.representative_point.longitude}）`:''}{report.city.grid?.latitude!=null?`；返回网格 ${report.city.grid.latitude}, ${report.city.grid.longitude}，高程 ${report.city.grid.elevation==null?'未提供':report.city.grid.elevation+' m'}`:''}</p>{!report.is_demo&&<p className="small">统一采用北京时间 UTC+08:00 日窗口；nearest 网格选择，关闭高程降尺度。代表点不等于城市或所属地区平均。{coordinateSource&&<a className="source-link" href={coordinateSource} target="_blank" rel="noreferrer"> 坐标核对来源 ↗</a>}</p>}<p className="small">报告 {report.report_id} · {report.review_status}</p>{report.source.url&&<a href={report.source.url} target="_blank" rel="noreferrer" className="source-link">核查原始来源（需联网） ↗</a>}<p className="art-note-text">{ART_NOTE}</p></section>
    </article></Modal>}
    {method&&<Modal title="方法与来源" onClose={()=>setMethod(false)}><MethodContent version={report?.method_version||'v0.1'}/></Modal>}
    {poster&&<Modal title="图片预览" onClose={()=>setPoster(null)}><div className="poster-preview"><p className="eyebrow">1080 × 1440 / PNG</p><h2>{poster.name.replace('.png','').replaceAll('_',' · ')}</h2>{poster.isDemo&&<DemoNotice/>}<img src={poster.url} alt={`${poster.cityName}24节气概览图片，包含来源、年份和艺术评级说明`}/><a className="primary download-button" href={poster.url} download={poster.name}>保存 PNG 图片 ↓</a><p className="small muted">图片将在浏览器下载目录保存。若下载被拦截，请允许本机下载，或右键预览图片另存为。</p></div></Modal>}
  </>;
}
