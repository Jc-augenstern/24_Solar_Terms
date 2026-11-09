export type Status = 'alive' | 'critical' | 'departed' | 'insufficient_data';
export type MetricKey = 'temperature' | 'precipitation' | 'diurnal_range';
export type Action = 'light' | 'flower';
export interface RepresentativePoint {latitude:number|null;longitude:number|null;description:string;crs?:string;coordinate_system?:string;source_url?:string;source_name?:string;source?:{name:string;url:string;geonames_id?:number}}
export interface City { id:string; name:string; region?:string; category?:string; category_label?:string; aliases?:string[]; representative_point?:RepresentativePoint; report_id?:string; data_status:string; reason?:string|null; update_status?:string; update_reason?:string|null }
export interface Metric {key:MetricKey;name:string;unit:string;baseline:number|null;recent:number|null;delta:number|null;baseline_std:number|null;scale:number;weight:number;baseline_n:number;recent_n:number}
export interface Annual {year:number;start:string;end:string;valid:boolean;reason:string|null;temperature:number|null;precipitation:number|null;diurnal_range:number|null}
export interface Term {id:string;name:string;season:string;order:number;status:Status;score:number|null;score_display:string;reason:string|null;summary:string;culture:{text:string;source_name:string;source_url:string};historical_portrait:string;metrics:Metric[];annual:Annual[];sensitivity:{sensitive:boolean;changes:unknown[]}}
export interface Report {schema_version:string;report_id:string;is_demo:boolean;city:{id:string;name:string;region?:string;category?:string;representative_point:RepresentativePoint;grid:{latitude:number|null;longitude:number|null;elevation:number|null}|null};data_status:string;baseline:{start:number;end:number};recent:{start:number;end:number};source:{name:string;url:string;model:string;attribution:string;description:string;request_parameters?:Record<string,unknown>};method_version:string;generated_at:string;summary:string;review_status:string;quality:Record<string,unknown>;terms:Term[]}
export interface Tributes {total:number;light:number;flower:number;terms:Record<string,{light:number;flower:number}>;recorded:{term_id:string;action:Action}[];recorded_now?:boolean}
export const labels:Record<Status,string> = {alive:'健在',critical:'病危',departed:'已故',insufficient_data:'资料不足'};
export const ART_NOTE = '本作品以历史气候差异生成艺术评级；“已故”不代表节气在天文学上消失。';
export const DEMO_NOTE = '演示样例，非真实气候结论';
export const number = (n:number|null|undefined, signed=false) => n == null ? '—' : `${signed && n > 0 ? '+' : ''}${n.toFixed(2)}`;
export const periods = (r:Report) => `${r.baseline.start}—${r.baseline.end} / ${r.recent.start}—${r.recent.end}`;
