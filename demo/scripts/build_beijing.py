"""Acquire explicit ERA5 caches, compute astronomical windows, publish Beijing report.

Normal app startup never imports this script. Network is preparation-only.
Usage: python scripts/build_beijing.py [--offline] [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from climate import DATA, TERMS, common_report, make_term, methodology, write_json

API = "https://archive-api.open-meteo.com/v1/archive"
EPHEMERIS_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp"
POINT = {"latitude": 39.9042, "longitude": 116.4074,
         "description": "北京中心城区代表点（固定坐标）；不是气象站，也不代表全市平均。"}
VARIABLES = ("temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "precipitation_sum")
PARAMETERS = {"latitude": POINT["latitude"], "longitude": POINT["longitude"],
              "daily": ",".join(VARIABLES), "models": "era5", "timezone": "Asia/Shanghai",
              "temperature_unit": "celsius", "precipitation_unit": "mm",
              "cell_selection": "nearest", "elevation": "nan"}
RAW = DATA / "raw"
BEIJING_RAW = RAW / "beijing"
BEIJING_TIME = timezone(timedelta(hours=8))
_last_weather_request = 0.0


def log(message):
    print(message, flush=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(content):
    return hashlib.sha256(content).hexdigest()


def request_bytes(url, params=None):
    import urllib.error
    import urllib.parse
    import urllib.request
    request_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    proxies = urllib.request.getproxies()
    # Python ignores the Windows proxy registry when only NO_PROXY is present.
    # Read the user's existing setting for this process; never alter the registry.
    if sys.platform == "win32" and not proxies.get("https") and not os.environ.get("HTTPS_PROXY"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                server = winreg.QueryValueEx(key, "ProxyServer")[0]
            if enabled and server:
                if "=" in server:
                    pairs = dict(piece.split("=", 1) for piece in server.split(";") if "=" in piece)
                    address = pairs.get("https") or pairs.get("http")
                else:
                    address = server
                if address:
                    proxies["https"] = address if "://" in address else "http://" + address
        except (OSError, ValueError):
            pass
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    errors = []
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(request_url, headers={"User-Agent": "Seasonal-Portraits-Local-Demo/0.1 (research; noncommercial)"})
            with opener.open(request, timeout=60) as response:
                return response.read(), response.url, {"content_type": response.headers.get("content-type"), "status": response.status}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = f"attempt {attempt}/3: {type(exc).__name__}: {exc}"
            errors.append(error)
            log(error)
            failure = {"at": now(), "url": url, "parameters": params, "attempt": attempt, "error": str(exc)}
            RAW.mkdir(parents=True, exist_ok=True)
            with (RAW / "request_failures.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(failure, ensure_ascii=False) + "\n")
            if attempt < 3:
                time.sleep(3 * attempt)
    raise RuntimeError("; ".join(errors))


def load_chunk(start, end, offline=False, refresh=False):
    global _last_weather_request
    params = {**PARAMETERS, "start_date": start, "end_date": end}
    identity = sha(json.dumps(params, sort_keys=True).encode())[:12]
    path = BEIJING_RAW / f"era5_{start}_{end}_{identity}.json"
    meta_path = path.with_suffix(".meta.json")
    if path.exists() and meta_path.exists() and not refresh:
        content = path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["sha256"] != sha(content) or meta["parameters"] != params:
            raise RuntimeError(f"缓存校验失败：{path.name}；保留文件供检查，请显式 --refresh 重新获取。")
        log(f"Cache: {start} to {end}")
    else:
        if offline:
            raise FileNotFoundError(f"离线缓存缺失：{path.name}；联网运行本脚本补齐。")
        # Long archive ranges count as multiple calls. Space five-year requests
        # to stay below the free API's per-minute allowance, even on fast links.
        remaining = 16.0 - (time.monotonic() - _last_weather_request)
        if remaining > 0:
            time.sleep(remaining)
        log(f"Download ERA5: {start} to {end}")
        _last_weather_request = time.monotonic()
        content, url, headers = request_bytes(API, params)
        # Validate before replacing existing raw cache.
        payload = json.loads(content)
        if payload.get("error"):
            raise RuntimeError(str(payload))
        BEIJING_RAW.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(content)
        temp.replace(path)
        meta = {"retrieved_at": now(), "url": url, "parameters": params,
                "sha256": sha(content), "response_headers": headers,
                "model": "ERA5", "fixed_grid_policy": "nearest; elevation=nan disables elevation downscaling"}
        write_json(meta_path, meta)
    payload = json.loads(content)
    return payload, {**meta, "cache_file": str(path.relative_to(DATA)).replace("\\", "/")}


def validate_chunk(payload, start, end, point=None):
    point = POINT if point is None else point
    if payload.get("utc_offset_seconds") != 28800:
        raise ValueError("API时区不是固定北京时间UTC+08:00")
    if payload.get("timezone") != "Asia/Shanghai":
        raise ValueError("API返回了错误时区")
    if abs(payload["latitude"] - point["latitude"]) > .5 or abs(payload["longitude"] - point["longitude"]) > .5:
        raise ValueError("返回网格偏离代表点超过0.5度")
    units = payload["daily_units"]
    for key in VARIABLES:
        expected = "mm" if key == "precipitation_sum" else "°C"
        if units.get(key) != expected:
            raise ValueError(f"单位错误 {key}: {units.get(key)}")
    daily = payload["daily"]
    dates = daily["time"]
    expected_dates = []
    cursor = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    while cursor <= finish:
        expected_dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    if dates != expected_dates:
        raise ValueError("日期不连续、重复、越界或次序错误；拒绝替代真实缺口。")
    if any(len(daily[key]) != len(dates) for key in VARIABLES):
        raise ValueError("变量长度与日期数量不匹配")
    rows = {}
    for i, stamp in enumerate(dates):
        row = {key: daily[key][i] for key in VARIABLES}
        for key, value in row.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"非法数值：{stamp} {key}")
            if key == "precipitation_sum" and value < 0:
                raise ValueError(f"负降水：{stamp}")
            if key != "precipitation_sum" and not -90 <= value <= 65:
                raise ValueError(f"超出物理检查范围的温度：{stamp} {key}")
        low, high, mean = row["temperature_2m_min"], row["temperature_2m_max"], row["temperature_2m_mean"]
        if low is not None and high is not None and low > high:
            raise ValueError(f"最高温低于最低温：{stamp}")
        if mean is not None and low is not None and high is not None and not low - .11 <= mean <= high + .11:
            raise ValueError(f"日均温不在极值范围：{stamp}")
        rows[stamp] = row
    return rows


def astronomical_windows(offline=False):
    import skyfield
    from skyfield import almanac, almanac_east_asia
    from skyfield.api import Loader, load_file

    astro_dir = RAW / "astronomy"
    ephemeris = astro_dir / "de421.bsp"
    eph_meta_path = astro_dir / "de421.meta.json"
    dates_path = astro_dir / "solar_terms_1961_2026.json"
    astro_dir.mkdir(parents=True, exist_ok=True)
    if not ephemeris.exists():
        if offline:
            raise FileNotFoundError("DE421星历缓存缺失；需先联网准备。")
        log("Download official JPL DE421 ephemeris")
        content, url, headers = request_bytes(EPHEMERIS_URL)
        if len(content) < 10_000_000 or not content.startswith(b"DAF/SPK"):
            raise ValueError("下载内容不是有效的DE421星历")
        temp = ephemeris.with_suffix(".tmp")
        temp.write_bytes(content)
        temp.replace(ephemeris)
        write_json(eph_meta_path, {"url": url, "retrieved_at": now(), "sha256": sha(content), "bytes": len(content), "response_headers": headers})
    eph_meta = json.loads(eph_meta_path.read_text(encoding="utf-8"))
    if sha(ephemeris.read_bytes()) != eph_meta["sha256"]:
        raise ValueError("DE421校验失败")
    version = skyfield.__version__
    if dates_path.exists():
        cache = json.loads(dates_path.read_text(encoding="utf-8"))
        if cache["skyfield_version"] == version and cache["ephemeris_sha256"] == eph_meta["sha256"]:
            return cache["events"], {key: value for key, value in cache.items() if key != "events"}
    loader = Loader(str(astro_dir))
    ts = loader.timescale(builtin=True)
    eph = load_file(str(ephemeris))
    calc = almanac_east_asia.solar_terms(eph)
    events = []
    by_name = {term["name"]: term for term in TERMS}
    for year in range(1961, 2027):
        log(f"Astronomical solar terms: {year}")
        times, indices = almanac.find_discrete(ts.utc(year, 1, 1), ts.utc(year + 1, 1, 1), calc)
        for instant, index in zip(times, indices):
            local = instant.utc_datetime().astimezone(BEIJING_TIME)
            name = almanac_east_asia.SOLAR_TERMS_ZHS[int(index)]
            events.append({"id": by_name[name]["id"], "name": name, "year": local.year,
                           "instant_utc": instant.utc_iso(), "instant_beijing": local.isoformat(), "date": local.date().isoformat()})
    events.sort(key=lambda item: item["instant_utc"])
    counts = Counter(event["year"] for event in events)
    if any(counts[year] != 24 for year in range(1961, 2027)):
        raise ValueError("某年份交节事件不是24项")
    checks = [{"year": 2025, "term": name, "expected": expected,
               "actual": next(e["date"] for e in events if e["year"] == 2025 and e["name"] == name)}
              for name, expected in (("立春", "2025-02-03"), ("春分", "2025-03-20"), ("冬至", "2025-12-21"))]
    if any(check["expected"] != check["actual"] for check in checks):
        raise ValueError("2025香港天文台历表抽样校验不通过")
    metadata = {"skyfield_version": version, "ephemeris": "JPL DE421", "ephemeris_sha256": eph_meta["sha256"],
                "timezone": "UTC+08:00", "timescale": "Skyfield builtin timescale tables (no live network)",
                "calendar_checks": checks, "calendar_check_source": "https://www.hko.gov.hk/en/gts/time/calendar/pdf/files/2025e.pdf",
                "generated_at": now()}
    write_json(dates_path, {**metadata, "events": events})
    eph.close()
    return events, metadata


def aggregate_window(rows, start, next_start):
    expected = (next_start - start).days
    dates = [(start + timedelta(days=i)).isoformat() for i in range(expected)]
    records = [rows.get(d, {}) for d in dates]
    values = {key: [r[key] for r in records if r.get(key) is not None] for key in VARIABLES}
    pairs = [r["temperature_2m_max"] - r["temperature_2m_min"] for r in records
             if r.get("temperature_2m_max") is not None and r.get("temperature_2m_min") is not None]
    counts = {key: len(v) for key, v in values.items()}
    counts["diurnal_pairs"] = len(pairs)
    invalid = [key for key, count in counts.items() if count / expected < .90]
    valid = not invalid
    reason = None if valid else "有效日数不足90%：" + ", ".join(f"{key}={counts[key]}/{expected}" for key in invalid)
    return {"year": start.year, "start": start.isoformat(), "end": (next_start - timedelta(days=1)).isoformat(),
            "next_start": next_start.isoformat(), "expected_days": expected, "valid_days": counts,
            "valid": valid, "reason": reason,
            "temperature": statistics.mean(values["temperature_2m_mean"]) if valid else None,
            "precipitation": statistics.mean(values["precipitation_sum"]) if valid else None,
            "diurnal_range": statistics.mean(pairs) if valid else None}


def build(offline=False, refresh=False):
    """Compatible Beijing entry; all acquisition now uses the shared safe runner."""
    from build_cities import main, read_json
    arguments = ["--city", "beijing"]
    if offline:
        arguments.append("--offline")
    if refresh:
        arguments.append("--refresh")
    if main(arguments):
        raise RuntimeError("北京数据任务未完成，现有报告保留；查看 data/batch_tasks.json 并续跑。")
    return read_json(DATA / "reports" / "beijing.json")


if __name__ == "__main__":
    from build_cities import main
    raise SystemExit(main(["--city", "beijing", *sys.argv[1:]]))
