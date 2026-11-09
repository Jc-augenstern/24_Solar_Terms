import { parseReport } from './report';

export class ApiError extends Error {
  code:string;
  status?:number;
  constructor(code:string,message:string,status?:number){super(message);this.name='ApiError';this.code=code;this.status=status}
}

function requestLabel(path:string){return /^\/cities\/[^/]+\/report$/.test(path)?'城市报告':'本机接口'}

async function serviceIsRunning():Promise<boolean> {
  const controller=new AbortController(),timer=window.setTimeout(()=>controller.abort(),2000);
  try{const response=await fetch('/api/health',{cache:'no-store',signal:controller.signal});return response.ok&&(await response.json()).ok===true}
  catch{return false}finally{window.clearTimeout(timer)}
}

export async function api<T>(path:string, options:RequestInit={},labelOverride?:string):Promise<T> {
  const label=labelOverride||requestLabel(path);
  const controller=new AbortController(),timer=window.setTimeout(()=>controller.abort(),15000);
  const cancel=()=>controller.abort(options.signal?.reason);
  options.signal?.addEventListener('abort',cancel,{once:true});
  if(options.signal?.aborted)cancel();
  let response:Response;
  try{
    // Relative URL deliberately follows the actual launcher-selected port.
    const headers=new Headers(options.headers);
    if(options.body&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
    try{response=await fetch(`/api/v1${path}`,{...options,cache:'no-store',signal:controller.signal,headers})}
    catch(e){
      if(options.signal?.aborted)throw new DOMException('请求已取消','AbortError');
      if(controller.signal.aborted)throw new ApiError('request_timeout',`${label}请求超时。请检查本机服务日志后重试。`);
      if(!(e instanceof TypeError))throw e;
      const alive=await serviceIsRunning();
      throw new ApiError(alive?'request_interrupted':'service_unreachable',alive
        ?`本机服务仍在运行，但${label}请求被中断或拦截。请点击“重新尝试”；若持续失败，请检查浏览器的本机访问权限或代理设置。`
        :`本机服务未启动、已关闭或当前地址无法访问（${location.origin}）。请运行“启动作品.cmd”，使用它打开的地址后重试。`);
    }
    let raw:string;
    try{raw=await response.text()}
    catch{throw new ApiError(controller.signal.aborted?'request_timeout':'response_interrupted',`${label}${controller.signal.aborted?'读取超时':'响应传输中断'}，请重新尝试。`,response.status)}
    let body:unknown;
    try{body=JSON.parse(raw)}
    catch{throw new ApiError(response.ok?'response_parse_failed':'http_error',response.ok
      ?`${label}解析失败：接口返回的内容不是有效 JSON。请检查本地报告或重新构建当前版本。`
      :`${label}接口返回 HTTP ${response.status}，响应不是有效 JSON；这不等于本机服务未启动。`,response.status)}
    if(!response.ok){
      const detail=body&&typeof body==='object'&&'detail' in body?body.detail:null;
      const error=detail&&typeof detail==='object'?detail as {code?:string;message?:string}:null;
      throw new ApiError(error?.code||'http_error',error?.message||(typeof detail==='string'?detail:`${label}请求失败（HTTP ${response.status}）。`),response.status);
    }
    if(!body||typeof body!=='object')throw new ApiError('response_schema_mismatch',`${label}返回的数据结构不正确。`,response.status);
    return body as T;
  }finally{window.clearTimeout(timer);options.signal?.removeEventListener('abort',cancel)}
}

export async function getReport(cityId:string,cityName=cityId,signal?:AbortSignal){
  const body=await api<unknown>(`/cities/${encodeURIComponent(cityId)}/report`,{signal},`${cityName}报告`);
  try{return parseReport(body,cityId)}
  catch(e){throw new ApiError('report_schema_mismatch',`${cityName}报告字段不兼容：${e instanceof Error?e.message:'报告结构无效'}。请恢复当前版本报告；不会改用样例数据。`)}
}
const STORAGE_KEY='jieqi-memorial-experience-v1';
export function experience():string {
  const old=localStorage.getItem(STORAGE_KEY);
  if(old) return old;
  const id=crypto.randomUUID();localStorage.setItem(STORAGE_KEY,id);return id;
}
export function newExperience():string {const id=crypto.randomUUID();localStorage.setItem(STORAGE_KEY,id);return id}
export function requestKey(id:string,city:string,term:string,action:string):string {
  const key=`jieqi-request:${id}:${city}:${term}:${action}`;
  const old=localStorage.getItem(key);if(old)return old;
  const value=crypto.randomUUID();localStorage.setItem(key,value);return value;
}
