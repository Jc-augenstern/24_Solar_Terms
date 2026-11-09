"""Single local city registry shared by preparation and runtime API."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / 'config' / 'cities.json'

@lru_cache(maxsize=1)
def get_cities() -> list[dict]:
    data = json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
    cities = data['cities']
    if len(cities) != 34 or len({c['id'] for c in cities}) != 34:
        raise ValueError('城市注册表必须恰好包含34个唯一城市')
    for city in cities:
        point = city['representative_point']
        if point['crs'] != 'WGS84' or not point.get('source'):
            raise ValueError('代表点缺少WGS84来源')
        if city['time_window']['utc_offset_seconds'] != 28800:
            raise ValueError('城市窗口口径不一致')
    return cities

def get_city(city_id: str) -> dict:
    return next((city for city in get_cities() if city['id'] == city_id), None) or _unknown(city_id)

def _unknown(city_id):
    raise KeyError(city_id)
