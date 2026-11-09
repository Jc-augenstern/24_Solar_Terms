"""Offline report contract used before publication and by the local service."""
from __future__ import annotations
import math
import json
from datetime import date
from pathlib import Path
from functools import lru_cache

from scripts.city_registry import get_city
from scripts.climate import TERMS, make_term, classify, display_score, report_summary
from scripts.report_schema import Report

@lru_cache(maxsize=1)
def _calendar():
    path=Path(__file__).resolve().parents[1]/'data/raw/astronomy/solar_terms_1961_2026.json'
    calendar=json.loads(path.read_text(encoding='utf-8'))
    events=calendar['events']
    return calendar, {(event['year'],event['id']):(event['date'],following['date'])
                      for event,following in zip(events,events[1:]) if 1961<=event['year']<=2025}

def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    if isinstance(value, dict):
        for child in value.values(): finite_tree(child)
    elif isinstance(value, list):
        for child in value: finite_tree(child)

def _equal(actual, expected, context):
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if isinstance(actual, bool) or not isinstance(actual, (float,int)) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f'{context}: calculation mismatch')
    elif isinstance(expected, dict):
        if not isinstance(actual, dict): raise ValueError(f'{context}: object missing')
        for k,v in expected.items():
            if k not in actual: raise ValueError(f'{context}.{k}: missing')
            _equal(actual[k],v,f'{context}.{k}')
    elif isinstance(expected, list):
        if not isinstance(actual,list) or len(actual)!=len(expected): raise ValueError(f'{context}: list mismatch')
        for i,(a,b) in enumerate(zip(actual,expected)): _equal(a,b,f'{context}[{i}]')
    elif actual != expected:
        raise ValueError(f'{context}: mismatch')

def validate_report(raw: dict, city_id: str) -> dict:
    finite_tree(raw)
    report=Report.model_validate(raw)
    demo=city_id=='demo'
    if report.city.id!=city_id or report.is_demo != demo or report.data_status != ('demo' if demo else 'ready'):
        raise ValueError('identity/mode mismatch')
    if (report.baseline.start,report.baseline.end,report.recent.start,report.recent.end)!=(1961,1990,1996,2025):
        raise ValueError('period mismatch')
    by_id={t['id']:t for t in raw['terms']}
    if set(by_id)!={t['id'] for t in TERMS} or len(raw['terms'])!=24:
        raise ValueError('24 unique solar terms required')
    for definition in TERMS:
        term=by_id[definition['id']]
        for key in ('name','season','order'): _equal(term[key],definition[key],key)
        if {m['key'] for m in term['metrics']} != {'temperature','precipitation','diurnal_range'} or len(term['metrics'])!=3:
            raise ValueError('metric identities invalid')
        if term['status']!=classify(term['score']) or term['score_display']!=display_score(term['score']):
            raise ValueError('score/status mismatch')
        if term['status']=='insufficient_data' and not term['reason']:
            raise ValueError('missing quality reason')
    if demo:
        if report.city.name!='样例城': raise ValueError('demo must not impersonate a city')
        return raw
    city=get_city(city_id)
    if raw['city']['name']!=city['name'] or raw['report_id']!=city['report_id']:
        raise ValueError('report/registry identity mismatch')
    point=city['representative_point']
    for key in ('latitude','longitude'):
        _equal(raw['city']['representative_point'][key],point[key],f'point.{key}')
    source=raw['source']
    if source['model'].lower()!='era5' or source.get('api')!='https://archive-api.open-meteo.com/v1/archive':
        raise ValueError('fixed ERA5 provider required')
    params=source['request_parameters']
    _equal(params,{'latitude':point['latitude'],'longitude':point['longitude'],'models':'era5','timezone':'Asia/Shanghai',
                   'daily':'temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum',
                   'temperature_unit':'celsius','precipitation_unit':'mm','cell_selection':'nearest','elevation':'nan'},'request')
    manifest=source.get('requests_manifest','')
    if not isinstance(manifest,str):
        raise ValueError('raw manifest path must be a string')
    legacy_manifest=manifest==f'raw/{city_id}/request_manifest.json'
    versioned_manifest=(manifest.startswith(f'raw/{city_id}/manifests/') and manifest.endswith('.json')
                        and len(Path(manifest).parts)==4 and '..' not in Path(manifest).parts)
    if not (legacy_manifest or versioned_manifest):
        raise ValueError('city raw manifest mismatch')
    grid=raw['city']['grid']
    if not grid or any(not isinstance(grid.get(k),(float,int)) for k in ('latitude','longitude','elevation')):
        raise ValueError('grid/elevation missing')
    if any(abs(grid[k]-point[k])>.5 for k in ('latitude','longitude')):
        raise ValueError('grid too far from representative point')
    quality=raw['quality']
    calendar,windows=_calendar()
    if any(quality.get(k) is not True for k in ('units_checked','grid_consistent','daily_extrema_checked')):
        raise ValueError('quality checks missing')
    if quality.get('astronomy',{}).get('timezone')!='UTC+08:00':
        raise ValueError('calendar timezone mismatch')
    for key in ('ephemeris_sha256','skyfield_version'):
        if quality['astronomy'].get(key)!=calendar[key]:
            raise ValueError('astronomical method version mismatch')
    first,last=date.fromisoformat(quality['date_start']),date.fromisoformat(quality['date_end'])
    if first!=date(1961,1,1) or quality['daily_rows']!=(last-first).days+1 or quality['duplicate_dates']!=0 or quality['missing_days']!=0:
        raise ValueError('daily coverage declaration mismatch')
    for definition in TERMS:
        term=by_id[definition['id']]
        annual=term['annual']
        if [a['year'] for a in annual]!=list(range(1961,2026)):
            raise ValueError('continuous 65-year series required')
        for a in annual:
            start,end=date.fromisoformat(a['start']),date.fromisoformat(a['end'])
            calendar_start,calendar_next=windows[(a['year'],definition['id'])]
            if a['start']!=calendar_start or a.get('next_start')!=calendar_next or (date.fromisoformat(calendar_next)-end).days!=1:
                raise ValueError('annual window differs from shared astronomical calendar')
            if start<first or end>last:
                raise ValueError('annual window outside acquired coverage')
            expected=(end-start).days+1
            if start.year!=a['year'] or not 13<=expected<=17 or a['expected_days']!=expected:
                raise ValueError('annual date window invalid')
            counts=a['valid_days']
            keys=('temperature_2m_mean','temperature_2m_max','temperature_2m_min','precipitation_sum','diurnal_pairs')
            if any(type(counts.get(k)) is not int or not 0<=counts[k]<=expected for k in keys):
                raise ValueError('invalid valid-day counts')
            valid=all(counts[k]/expected>=.9 for k in keys)
            if valid != a['valid'] or (not valid and not a['reason']):
                raise ValueError('90% quality gate mismatch')
            for key in ('temperature','precipitation','diurnal_range'):
                if (a[key] is not None) != valid: raise ValueError('invalid annual missing values')
        calculated=make_term(definition,annual)
        for key in ('metrics','score','score_display','status','summary','historical_portrait','sensitivity'):
            _equal(term[key],calculated[key],f"{definition['id']}.{key}")
        valid_years={'baseline':calculated['metrics'][0]['baseline_n'],'recent':calculated['metrics'][0]['recent_n']}
        _equal(quality['valid_years'][definition['id']],valid_years,'quality.valid_years')
    expected_summary=report_summary(raw['terms'],False).replace('北京代表点',f"{city['name']}代表点",1)
    if raw['summary']!=expected_summary:
        raise ValueError('city summary does not match calculations')
    if quality.get('complete_terms') != sum(t['status']!='insufficient_data' for t in raw['terms']):
        raise ValueError('quality term count mismatch')
    if set(quality['sensitive_terms'])!={t['id'] for t in raw['terms'] if t['sensitivity']['sensitive']}:
        raise ValueError('sensitivity list mismatch')
    return raw
