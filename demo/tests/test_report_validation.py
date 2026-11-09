"""Reject plausible but inconsistent real reports, using temporary copies only."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from scripts.report_validation import validate_report
from scripts.city_registry import get_cities

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def beijing():
    return json.loads((ROOT/'data/reports/beijing.json').read_text(encoding='utf-8'))

def test_registry_scope_and_original_report(beijing):
    cities=get_cities()
    from collections import Counter
    assert Counter(c['category'] for c in cities)=={'直辖市':4,'大陆省会':22,'自治区首府':5,'港澳台代表城市':3}
    assert len({c['region'] for c in cities})==34
    assert {'beijing','harbin','xian','shanghai','chengdu','guangzhou'} <= {c['id'] for c in cities}
    assert validate_report(beijing,'beijing') is beijing

@pytest.mark.parametrize('damage',[
    lambda r:r['city']['representative_point'].update(latitude=31.2),
    lambda r:r['source']['request_parameters'].update(models='best_match'),
    lambda r:r['source']['request_parameters'].update(timezone='auto'),
    lambda r:r['source'].update(requests_manifest='raw/shanghai/request_manifest.json'),
    lambda r:r['terms'][0]['metrics'][0].update(unit='F'),
    lambda r:r['terms'][0]['metrics'][0].update(baseline_std=99),
    lambda r:r['terms'][0]['annual'][0]['valid_days'].update(diurnal_pairs=0),
    lambda r:r['terms'][0]['annual'].pop(),
    lambda r:r['terms'][0]['sensitivity'].update(sensitive=False),
    lambda r:r.update(summary='北京代表点：健在24项。'),
])
def test_damaged_real_report_cannot_be_published(beijing,damage):
    damage(beijing)
    with pytest.raises((ValueError,KeyError,TypeError)):
        validate_report(beijing,'beijing')

def test_preparation_states_and_failed_update_keep_last_report(tmp_path,beijing):
    data=tmp_path/'data'; (data/'reports').mkdir(parents=True)
    tasks={'cities':{'harbin':{'status':'blocked','last_error':'HTTP 429 daily quota'},'shanghai':{'status':'fetching'},'xian':{'status':'invalid_report','last_error':'bad units'},'beijing':{'status':'failed','last_error':'update interrupted'}}}
    (data/'batch_tasks.json').write_text(json.dumps(tasks),encoding='utf-8')
    (data/'reports/beijing.json').write_text(json.dumps(beijing),encoding='utf-8')
    client=TestClient(create_app(data,data/'isolated.sqlite3'))
    cities={c['id']:c for c in client.get('/api/v1/cities').json()['cities']}
    assert cities['harbin']['data_status']=='acquisition_blocked'
    assert cities['shanghai']['data_status']=='preparing'
    assert cities['xian']['data_status']=='invalid_report'
    assert cities['beijing']['data_status']=='ready'
    assert '上一份有效报告' in cities['beijing']['reason']
    assert client.get('/api/v1/cities/beijing/report').json()['terms']==beijing['terms']
    assert client.get('/api/v1/cities/harbin/report').status_code==503
