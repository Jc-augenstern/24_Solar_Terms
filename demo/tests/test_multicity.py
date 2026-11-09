"""Multicity API integration against genuine reports, isolated SQLite only."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import create_app
from scripts.city_registry import get_cities


@pytest.fixture
def multi(tmp_path):
    data = tmp_path / 'data'; (data / 'reports').mkdir(parents=True)
    available = []
    for city in get_cities():
        source = ROOT / 'data' / 'reports' / f'{city["id"]}.json'
        if source.is_file():
            shutil.copyfile(source, data / 'reports' / source.name)
            available.append(city['id'])
    shutil.copyfile(ROOT / 'data' / 'reports' / 'demo.json', data / 'reports' / 'demo.json')
    (data / 'report_manifest.json').write_text(json.dumps({'installed': available + ['demo']}), encoding='utf-8')
    db = tmp_path / 'isolated.sqlite3'
    return data, db, TestClient(create_app(data_dir=data, db_path=db)), available


def test_registry_exact_coverage_and_actual_report_availability(multi):
    data, _, client, available = multi
    response = client.get('/api/v1/cities')
    assert response.status_code == 200
    cities = response.json()['cities']
    assert len(cities) == len({c['id'] for c in cities}) == 34
    assert {c['category'] for c in cities} == {'直辖市', '大陆省会', '自治区首府', '港澳台代表城市'}
    for city in cities:
        assert city['region'] and city['aliases']
        assert (city['data_status'] == 'ready') == (city['id'] in available)
    path = data / 'reports' / 'beijing.json'
    original = path.read_bytes()
    path.write_text('{invalid', encoding='utf-8')
    entries = client.get('/api/v1/cities').json()['cities']
    assert next(c for c in entries if c['id'] == 'beijing')['data_status'] == 'invalid_report'
    assert client.get('/api/v1/cities/beijing/report').json()['detail']['code'] == 'report_parse_failed'
    path.write_bytes(original)


def test_real_city_identity_and_coordinate_mismatch_rejected(multi):
    data, _, client, _ = multi
    path = data / 'reports' / 'beijing.json'; original = path.read_text(encoding='utf-8')
    value = json.loads(original); value['city']['id'] = 'shanghai'
    path.write_text(json.dumps(value), encoding='utf-8')
    assert client.get('/api/v1/cities/beijing/report').json()['detail']['code'] == 'report_schema_mismatch'
    value = json.loads(original); value['city']['representative_point']['latitude'] = 20
    path.write_text(json.dumps(value), encoding='utf-8')
    assert client.get('/api/v1/cities/beijing/report').json()['detail']['code'] == 'report_schema_mismatch'


def test_real_cities_same_term_actions_isolated_and_persisted(multi):
    data, db, client, available = multi
    if len(available) < 2:
        pytest.skip('Requires two actually published independent real reports')
    first, second = available[:2]
    exp = str(uuid4())
    def endpoint(city): return f'/api/v1/cities/{city}/tributes'
    def body(action='light'): return {'experience_id': exp, 'term_id': 'lichun', 'action': action, 'idempotency_key': str(uuid4())}
    request = body()
    response = client.post(endpoint(first), json=request)
    assert response.status_code == 200 and response.json()['recorded_now'] is True
    assert client.post(endpoint(first), json=request).json()['recorded_now'] is False
    assert client.post(endpoint(first), json=body()).json()['total'] == 1
    untouched = client.get(endpoint(second), params={'experience_id': exp}).json()
    assert untouched['total'] == 0 and untouched['recorded'] == []
    # An idempotency key cannot cross city boundaries and silently target another city.
    assert client.post(endpoint(second), json=request).status_code == 409
    assert client.post(endpoint(second), json=body()).json()['total'] == 1
    assert client.post(endpoint(first), json=body('flower')).json()['total'] == 2
    restarted = TestClient(create_app(data_dir=data, db_path=db))
    a = restarted.get(endpoint(first), params={'experience_id': exp}).json()
    b = restarted.get(endpoint(second), params={'experience_id': exp}).json()
    assert (a['total'], b['total']) == (2, 1)
    assert a['terms']['lichun'] == {'light': 1, 'flower': 1}
    assert b['terms']['lichun'] == {'light': 1, 'flower': 0}
    assert restarted.post(endpoint(first), json=request).json()['total'] == 2
    assert restarted.get('/api/v1/cities/demo/tributes').json()['total'] == 0
