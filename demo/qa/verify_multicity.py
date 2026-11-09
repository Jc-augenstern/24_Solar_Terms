"""Independent, read-only checks of published cities and their raw ERA5 evidence.

Uses only the standard library, never the implementation's calculation functions.
Missing cities are recorded as incomplete, not scientific insufficient-data ratings.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'qa' / 'multicity'
KEYS = ('temperature', 'precipitation', 'diurnal_range')
VARIABLES = ('temperature_2m_mean', 'temperature_2m_max', 'temperature_2m_min', 'precipitation_sum')
WEIGHTS = (.60, .25, .15)
STATES = ('alive', 'critical', 'departed', 'insufficient_data')
EXPECTED_NAMES = set('北京 天津 上海 重庆 石家庄 太原 沈阳 长春 哈尔滨 南京 杭州 合肥 福州 南昌 济南 郑州 武汉 长沙 广州 海口 成都 贵阳 昆明 西安 兰州 西宁 呼和浩特 南宁 拉萨 银川 乌鲁木齐 台北 香港 澳门'.split())


def read(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Invalid JSON number {x}')))
    def finite(v):
        if isinstance(v, float): assert math.isfinite(v), f'Non-finite numeric value in {path}'
        elif isinstance(v, dict):
            for child in v.values(): finite(child)
        elif isinstance(v, list):
            for child in v: finite(child)
    finite(value)
    return value


def close(actual, expected, label):
    assert (actual is None and expected is None) or (actual is not None and expected is not None and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-10)), (label, actual, expected)


def state(score, low=40, high=70):
    return 'insufficient_data' if score is None else 'alive' if score >= high else 'critical' if score >= low else 'departed'


def verify_term(term):
    annual = term['annual']
    assert [a['year'] for a in annual] == list(range(1961, 2026)), term['id']
    old = [a for a in annual if a['valid'] and 1961 <= a['year'] <= 1990]
    recent = [a for a in annual if a['valid'] and 1996 <= a['year'] <= 2025]
    assert set(m['key'] for m in term['metrics']) == set(KEYS)
    by_key = {m['key']: m for m in term['metrics']}
    deviations = []
    for key, weight in zip(KEYS, WEIGHTS):
        metric = by_key[key]
        a, b = [v[key] for v in old], [v[key] for v in recent]
        mean_a = statistics.mean(a) if a else None
        mean_b = statistics.mean(b) if b else None
        std = statistics.stdev(a) if len(a) >= 2 else None
        delta = mean_b - mean_a if mean_a is not None and mean_b is not None else None
        for field, expected in [('baseline', mean_a), ('recent', mean_b), ('baseline_std', std), ('delta', delta), ('baseline_n', len(a)), ('recent_n', len(b))]:
            close(metric[field], expected, f'{term["id"]}/{key}/{field}')
        assert metric['weight'] == weight and metric['minimum_scale'] == .5
        assert metric['unit'] == ('mm/日' if key == 'precipitation' else '℃')
        if delta is not None and std is not None:
            deviations.append(weight * abs(delta) / max(std, .5))
    enough = len(old) >= 27 and len(recent) >= 27
    score = 100 / (1 + sum(deviations)) if enough else None
    close(term['score'], score, f'{term["id"]}/score')
    assert term['status'] == state(score)
    if not enough:
        assert term['reason'] and term['score_display'] == '—'
    else:
        display = f'{score:.2f}'
        if score < 40 <= float(display): display = '<40'
        elif score < 70 <= float(display): display = '<70'
        assert term['score_display'] == display
        sensitivity = []
        metrics = [by_key[k] for k in KEYS]
        for i in range(3):
            for factor in (.9, 1.1):
                weights = list(WEIGHTS); weights[i] *= factor
                weights = [w / sum(weights) for w in weights]
                s = 100 / (1 + sum(w * abs(m['delta']) / max(m['baseline_std'], .5) for w, m in zip(weights, metrics)))
                sensitivity.append(state(s))
                minima = [.5] * 3; minima[i] *= factor
                s = 100 / (1 + sum(w * abs(m['delta']) / max(m['baseline_std'], minimum) for w, m, minimum in zip(WEIGHTS, metrics, minima)))
                sensitivity.append(state(s))
        sensitivity += [state(score, low=40 + d) for d in (-5, 5)]
        sensitivity += [state(score, high=70 + d) for d in (-5, 5)]
        assert len(term['sensitivity']['checks']) == 16
        assert term['sensitivity']['sensitive'] == any(s != state(score) for s in sensitivity)
    return {'id': term['id'], 'score': score, 'status': state(score), 'baseline_n': len(old), 'recent_n': len(recent)}


def raw_rows(report):
    manifest = read(ROOT / 'data' / report['source']['requests_manifest'])
    rows = {}
    point = report['city']['representative_point']
    for item in manifest['requests']:
        path = ROOT / 'data' / item['cache_file']
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == item['sha256'], path
        payload = json.loads(content)
        params = item['parameters']
        assert params['models'] == 'era5' and params['timezone'] == 'Asia/Shanghai'
        assert params['latitude'] == point['latitude'] and params['longitude'] == point['longitude']
        assert params['elevation'] == 'nan' and params['cell_selection'] == 'nearest'
        assert payload['utc_offset_seconds'] == 28800 and payload['timezone'] == 'Asia/Shanghai'
        for k in ('latitude', 'longitude', 'elevation'):
            close(payload[k], report['city']['grid'][k], f'grid/{k}')
        daily = payload['daily']
        for key in VARIABLES:
            assert payload['daily_units'][key] == ('mm' if key == 'precipitation_sum' else '°C')
            assert len(daily[key]) == len(daily['time'])
        expected = date.fromisoformat(params['start_date'])
        for i, stamp in enumerate(daily['time']):
            assert stamp == expected.isoformat() and stamp not in rows
            rows[stamp] = {k: daily[k][i] for k in VARIABLES}
            expected += timedelta(days=1)
        assert expected - timedelta(days=1) == date.fromisoformat(params['end_date'])
    assert min(rows) == report['quality']['date_start'] and max(rows) == report['quality']['date_end']
    assert len(rows) == report['quality']['daily_rows']
    assert len(rows) == (date.fromisoformat(max(rows)) - date.fromisoformat(min(rows))).days + 1
    return rows


def raw_audit(term, rows):
    checks = []
    for a in term['annual']:
        start, end = date.fromisoformat(a['start']), date.fromisoformat(a['end'])
        days = [rows[(start + timedelta(days=i)).isoformat()] for i in range((end - start).days + 1)]
        values = {k: [r[k] for r in days if r[k] is not None] for k in VARIABLES}
        paired = [r['temperature_2m_max'] - r['temperature_2m_min'] for r in days if r['temperature_2m_max'] is not None and r['temperature_2m_min'] is not None]
        valid = all(len(v) / len(days) >= .9 for v in values.values()) and len(paired) / len(days) >= .9
        assert valid == a['valid']
        computed = [statistics.mean(values['temperature_2m_mean']), statistics.mean(values['precipitation_sum']), statistics.mean(paired)] if valid else [None] * 3
        for key, value in zip(KEYS, computed): close(a[key], value, f'raw/{term["id"]}/{a["year"]}/{key}')
        checks.append({'year': a['year'], 'valid': valid})
    return {'id': term['id'], 'windows_checked': len(checks), 'passed': True}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    registry = read(ROOT / 'config' / 'cities.json')
    cities = registry['cities'] if isinstance(registry, dict) else registry
    assert len(cities) == 34 and len({c.get('id', c.get('city_id')) for c in cities}) == 34
    assert {c['name'] for c in cities} == EXPECTED_NAMES
    assert dict(Counter(c['category'] for c in cities)) == {'直辖市': 4, '大陆省会': 22, '自治区首府': 5, '港澳台代表城市': 3}
    astronomy = read(ROOT / 'data' / 'raw' / 'astronomy' / 'solar_terms_1961_2026.json')
    calendar = {(a['id'], a['year']): (a['date'], (date.fromisoformat(b['date']) - timedelta(days=1)).isoformat()) for a, b in zip(astronomy['events'], astronomy['events'][1:])}
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'registered_cities': 34, 'data_complete': 0, 'cities': [], 'failures': []}
    for city in cities:
        ident = city.get('id', city.get('city_id'))
        item = {'id': ident, 'name': city['name'], 'data': 'not_published', 'page': 'not_checked', 'chart': 'not_checked', 'memorial': 'not_checked', 'poster': 'not_checked'}
        report_path = ROOT / 'data' / 'reports' / f'{ident}.json'
        if report_path.exists():
            try:
                report = read(report_path)
                assert report['city']['id'] == ident and report['city']['name'] == city['name']
                assert report['is_demo'] is False and report['data_status'] == 'ready'
                assert report['source']['model'].lower() == 'era5'
                assert report['baseline'] == {'start': 1961, 'end': 1990} and report['recent'] == {'start': 1996, 'end': 2025}
                point = city.get('representative_point', city)
                assert report['city']['representative_point']['latitude'] == point['latitude']
                assert report['city']['representative_point']['longitude'] == point['longitude']
                assert len(report['terms']) == len({t['id'] for t in report['terms']}) == 24
                assert sorted(t['order'] for t in report['terms']) == list(range(1, 25))
                counts = dict(Counter(t['status'] for t in report['terms']))
                assert set(counts).issubset(STATES) and sum(counts.values()) == 24
                for status, label in zip(STATES, ('健在', '病危', '已故', '资料不足')):
                    assert f'{label}{counts.get(status, 0)}项' in report['summary']
                terms = [verify_term(t) for t in report['terms']]
                for term in report['terms']:
                    for annual in term['annual']:
                        assert (annual['start'], annual['end']) == calendar[(term['id'], annual['year'])], 'Astronomical daily window mismatch'
                rows = raw_rows(report)
                raw_checks = [raw_audit(t, rows) for t in report['terms'] if t['id'] in ('lichun', 'dongzhi')]
                item.update(data='passed', report_id=report['report_id'], generated_at=report['generated_at'], report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(), counts={s: counts.get(s, 0) for s in STATES}, terms=terms, raw_checks=raw_checks)
                result['data_complete'] += 1
            except Exception as exc:
                item.update(data='failed', error=f'{type(exc).__name__}: {exc}')
                result['failures'].append({'id': ident, 'error': item['error']})
        result['cities'].append(item)
    result['passed_for_published'] = not result['failures']
    result['all_34_data_complete'] = result['data_complete'] == 34 and not result['failures']
    (OUT / 'data-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'cities'}, ensure_ascii=False))
    return 1 if result['failures'] else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
