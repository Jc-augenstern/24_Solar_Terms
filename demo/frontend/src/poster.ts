import { ART_NOTE, DEMO_NOTE, labels, periods, type Report } from './types';

export async function makePoster(report:Report):Promise<Blob> {
  await document.fonts.ready;
  const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=1440;
  const ctx=canvas.getContext('2d');if(!ctx)throw new Error('浏览器无法创建图片画布，请更换浏览器重试。');
  const ink='#292c28',paper='#f1efe7',muted='#666a62',line='#cbcbbf';
  ctx.fillStyle=paper;ctx.fillRect(0,0,1080,1440);
  const text=(s:string,x:number,y:number,size=26,color=ink,serif=false)=>{ctx.font=`${size}px ${serif?'"SimSun", "Songti SC", serif':'"Microsoft YaHei", "PingFang SC", sans-serif'}`;ctx.fillStyle=color;ctx.fillText(s,x,y)};
  const wrap=(s:string,x:number,y:number,width:number,size:number,leading:number,maxLines=10,color=ink)=>{
    ctx.font=`${size}px "Microsoft YaHei", "PingFang SC", sans-serif`;ctx.fillStyle=color;
    const lines:string[]=[];let current='';for(const ch of s){if(ch==='\n'||ctx.measureText(current+ch).width>width){lines.push(current);current=ch==='\n'?'':ch}else current+=ch}if(current)lines.push(current);
    lines.slice(0,maxLines).forEach((v,i)=>ctx.fillText(i===maxLines-1&&lines.length>maxLines?v.slice(0,-1)+'…':v,x,y+i*leading));return y+Math.min(lines.length,maxLines)*leading;
  };
  ctx.strokeStyle=ink;ctx.lineWidth=2;ctx.strokeRect(40,40,1000,1360);
  text('节气讣告  /  家乡旧候纪念馆',72,94,25);
  text('地方气候档案 · 本地交互作品',72,135,21,muted);
  const departed=report.terms.filter(t=>t.status==='departed').length;
  const title=`${report.city.name} · ${departed?'城市讣告':'家乡守候卡'}`;
  let titleSize=64;ctx.font=`${titleSize}px "SimSun", "Songti SC", serif`;
  while(ctx.measureText(title).width>936&&titleSize>36){titleSize-=2;ctx.font=`${titleSize}px "SimSun", "Songti SC", serif`}
  text(title,72,226,titleSize,ink,true);
  if(report.is_demo){ctx.fillStyle='#dad2bc';ctx.fillRect(72,258,936,48);text(DEMO_NOTE,92,291,27,ink)}
  else text(departed?'我们纪念的，是家乡正在改变的季节模样。':'这份名单，暂时没有讣告。为下一次节气留下观察。',72,290,25,muted);
  const sorted=[...report.terms].sort((a,b)=>a.order-b.order);
  sorted.forEach((term,i)=>{
    const x=72+(i%4)*238,y=340+Math.floor(i/4)*100;
    ctx.strokeStyle=line;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y+84);ctx.lineTo(x+216,y+84);ctx.stroke();
    text(`${String(term.order).padStart(2,'0')}  ${term.name}`,x,y+24,31,ink,true);
    text(`${labels[term.status]}${term.sensitivity?.sensitive?'*':''}  ·  ${term.score==null?'无评级':term.score_display}`,x,y+61,21,muted);
  });
  text('旧候的变化',72,999,30,ink,true);
  wrap(report.summary,72,1042,930,24,36,3);
  text(`历史 ${report.baseline.start}—${report.baseline.end}  /  近期 ${report.recent.start}—${report.recent.end}`,72,1170,23);
  const source=report.is_demo?'来源：程序合成样例，仅用于交互验证':`来源：${report.source.name}`;
  wrap(source,72,1210,936,21,29,2,muted);
  text(`艺术指数 ${report.method_version} · 评级使用未舍入数值 · * 对参数敏感`,72,1271,20,muted);
  wrap(ART_NOTE,72,1313,936,22,32,2);
  text(`${report.city.name} · ${periods(report)} · 24节气${report.is_demo?'':` · WGS84 ${report.city.representative_point.latitude}, ${report.city.representative_point.longitude}`}`,72,1378,16,muted);
  return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('图片生成失败，请重新生成。')),'image/png'));
}
