"""Preparation-only gazetteer lookup. Never run on application startup."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from build_beijing import request_bytes, now, sha

ROOT = Path(__file__).resolve().parents[1]
# Names and administrative scope come from the project brief; coordinates must
# come from the retained gazetteer response, never this table.
ROWS = [
 ('beijing','北京','北京市','直辖市','Beijing','Beijing Municipality','CN'),
 ('tianjin','天津','天津市','直辖市','Tianjin','Tianjin Municipality','CN'),
 ('shanghai','上海','上海市','直辖市','Shanghai','Shanghai Municipality','CN'),
 ('chongqing','重庆','重庆市','直辖市','Chongqing','Chongqing Municipality','CN'),
 ('shijiazhuang','石家庄','河北省','大陆省会','Shijiazhuang','Hebei','CN'),
 ('taiyuan','太原','山西省','大陆省会','Taiyuan','Shanxi','CN'),
 ('shenyang','沈阳','辽宁省','大陆省会','Shenyang','Liaoning','CN'),
 ('changchun','长春','吉林省','大陆省会','Changchun','Jilin','CN'),
 ('harbin','哈尔滨','黑龙江省','大陆省会','Harbin','Heilongjiang','CN'),
 ('nanjing','南京','江苏省','大陆省会','Nanjing','Jiangsu','CN'),
 ('hangzhou','杭州','浙江省','大陆省会','Hangzhou','Zhejiang','CN'),
 ('hefei','合肥','安徽省','大陆省会','Hefei','Anhui','CN'),
 ('fuzhou','福州','福建省','大陆省会','Fuzhou','Fujian','CN'),
 ('nanchang','南昌','江西省','大陆省会','Nanchang','Jiangxi','CN'),
 ('jinan','济南','山东省','大陆省会','Jinan','Shandong','CN'),
 ('zhengzhou','郑州','河南省','大陆省会','Zhengzhou','Henan','CN'),
 ('wuhan','武汉','湖北省','大陆省会','Wuhan','Hubei','CN'),
 ('changsha','长沙','湖南省','大陆省会','Changsha','Hunan','CN'),
 ('guangzhou','广州','广东省','大陆省会','Guangzhou','Guangdong','CN'),
 ('haikou','海口','海南省','大陆省会','Haikou','Hainan','CN'),
 ('chengdu','成都','四川省','大陆省会','Chengdu','Sichuan','CN'),
 ('guiyang','贵阳','贵州省','大陆省会','Guiyang','Guizhou','CN'),
 ('kunming','昆明','云南省','大陆省会','Kunming','Yunnan','CN'),
 ('xian','西安','陕西省','大陆省会',"Xi'an",'Shaanxi','CN'),
 ('lanzhou','兰州','甘肃省','大陆省会','Lanzhou','Gansu','CN'),
 ('xining','西宁','青海省','大陆省会','Xining','Qinghai','CN'),
 ('hohhot','呼和浩特','内蒙古自治区','自治区首府','Hohhot','Inner Mongolia','CN'),
 ('nanning','南宁','广西壮族自治区','自治区首府','Nanning','Guangxi','CN'),
 ('lhasa','拉萨','西藏自治区','自治区首府','Lhasa','Tibet','CN'),
 ('yinchuan','银川','宁夏回族自治区','自治区首府','Yinchuan','Ningxia','CN'),
 ('urumqi','乌鲁木齐','新疆维吾尔自治区','自治区首府','Urumqi','Xinjiang','CN'),
 ('taipei','台北','台湾','港澳台代表城市','Taipei','Taiwan','TW'),
 ('hongkong','香港','香港特别行政区','港澳台代表城市','Hong Kong',None,'HK'),
 ('macau','澳门','澳门特别行政区','港澳台代表城市','Macau',None,'MO'),
]

def main():
    folder=ROOT/'data'/'raw'/'geocoding'; folder.mkdir(parents=True,exist_ok=True)
    cities=[]
    for ident,name,region,category,query,admin,cc in ROWS:
        path=folder/f'{ident}.json'
        params={'name':query,'count':100,'language':'en','format':'json','countryCode':cc}
        if not path.exists():
            body,url,headers=request_bytes('https://geocoding-api.open-meteo.com/v1/search',params)
            path.write_bytes(body)
            path.with_suffix('.meta.json').write_text(json.dumps({'url':url,'parameters':params,'retrieved_at':now(),'sha256':sha(body)},indent=2),encoding='utf-8')
            time.sleep(.4)
        data=json.loads(path.read_text(encoding='utf-8'))
        candidates=[r for r in data.get('results',[]) if r.get('country_code')==cc and r.get('feature_code') in ('PPLC','PPLA') and (admin is None or r.get('admin1')==admin)]
        if len(candidates)!=1:
            print(ident,'NEEDS REVIEW',json.dumps(data,ensure_ascii=False),flush=True)
            continue
        chosen=candidates[0]
        point={k:chosen[k] for k in ('latitude','longitude')}
        note='采用 GeoNames 城市居民地记录作为固定代表点；不是气象站，不代表全市或全省平均。'
        if ident=='beijing':
            point={'latitude':39.9042,'longitude':116.4074}
            note='保留已认可北京v0.1请求点；与GeoNames北京城市中心记录相距约0.94km，核对为同一中心城区，避免变更基线。'
        point.update(description=note,crs='WGS84',source={'name':'GeoNames via Open-Meteo Geocoding','url':f"https://www.geonames.org/{chosen['id']}/",'geonames_id':chosen['id'],'record':chosen,'response_file':f'raw/geocoding/{ident}.json','checked_at':now(),'license':'CC BY 4.0'})
        aliases=[query,ident,region.removesuffix('省').removesuffix('市'),name+'市']
        aliases += {'taipei':['臺北','台北市'],'hongkong':['Hongkong','Hong Kong','港'],'macau':['澳门','澳門','Macao','澳'],'urumqi':['乌市','Urumchi'],'hohhot':['呼市'],'xian':['西安市','Xi’an']}.get(ident,[])
        cities.append({'id':ident,'city_id':ident,'name':name,'region':region,'category':category,'aliases':sorted(set(aliases)),'representative_point':point,'time_window':{'timezone':'Asia/Shanghai','utc_offset_seconds':28800,'baseline':{'start':1961,'end':1990},'recent':{'start':1996,'end':2025},'annual_start':1961,'annual_end':2025,'rule':'交节北京时间日期起至下一交节日期前一日，按开始年份归档'},'report_id':f'{ident}-era5-v0.1'})
        print(ident,chosen['name'],chosen.get('admin1'),chosen['feature_code'],point['latitude'],point['longitude'],chosen.get('elevation'),flush=True)
    if len(cities)!=34: raise SystemExit(f'Only {len(cities)}/34 unambiguous; review retained responses before publishing registry')
    target=ROOT/'config'/'cities.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps({'schema_version':'1.0','coordinate_reference':'WGS84','coordinate_documentation':['https://www.geonames.org/about.html','https://open-meteo.com/en/docs/geocoding-api'],'cities':cities},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
