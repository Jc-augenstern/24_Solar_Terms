"""Resumable, single-worker ERA5 preparation. Never imported by normal startup.

python scripts/build_cities.py --all
python scripts/build_cities.py --resume
python scripts/build_cities.py --city beijing --offline
python scripts/build_cities.py --check
Exit 2 means a saved quota/network/data blocker; no failed report is published.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.city_registry import get_cities, get_city
from scripts.climate import TERMS, BASELINE, RECENT, common_report, make_term, write_json
from scripts import build_beijing as legacy

API = legacy.API
VARIABLES = legacy.VARIABLES
PRIORITY = ["beijing", "harbin", "xian", "shanghai", "chengdu", "guangzhou"]
POLICY = {
    "verified_at": "2026-10-29", "provider": "Open-Meteo free non-commercial API",
    "terms_url": "https://open-meteo.com/en/terms",
    "pricing_url": "https://open-meteo.com/en/pricing",
    "documentation_url": "https://open-meteo.com/en/docs/historical-weather-api",
    "official_limits": {"minute": 600, "hour": 5000, "day": 10000, "month": 300000},
    "default_conservative_limits": {"minute": 450, "hour": 4500, "day": 9000, "month": 270000},
    "estimated_call_formula": "max(1, days/14) * max(1, variables/10) * models * locations; each attempted request reserved before sending",
    "notes": "折算调用而非HTTP次数；按滚动时间窗口保守记账，已有本地天气请求及地理编码请求纳入。共享IP实际余量未知，服务429优先并停止整批。不会换IP/账号/代理绕过配额。",
    "use": "本地非商业作品的准备与研究，不购买资源。", "concurrency": 1,
    "attribution": "Weather data by Open-Meteo.com (CC BY 4.0), based on Copernicus Climate Change Service / ECMWF ERA5 reanalysis.",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "modification_notice": "原始ERA5逐日再分析经北京时间节气窗口聚合、两期统计及v0.1艺术指数计算。"
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError(f"非法JSON数值: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject)


def parameters(city):
    point = city["representative_point"]
    return {**legacy.PARAMETERS, "latitude": point["latitude"], "longitude": point["longitude"]}


def estimate_calls(params):
    days = (date.fromisoformat(params["end_date"]) - date.fromisoformat(params["start_date"])).days + 1
    return max(1.0, days / 14) * max(1.0, len(params["daily"].split(",")) / 10)


def required_periods(events, chunk_years=5):
    """Derive final cross-year day from the same calendar used for aggregation.

    Start at Jan 1 of the first event year to reuse the accepted Beijing cache;
    those few pre-event days never enter the solar-term statistics.
    """
    windows = [(event, following) for event, following in zip(events, events[1:])
               if BASELINE["start"] <= event["year"] <= RECENT["end"]]
    if len(windows) != (RECENT["end"] - BASELINE["start"] + 1) * 24:
        raise ValueError("节气日历不含连续65年完整窗口及下一交节边界")
    required_start = min(date.fromisoformat(event["date"]) for event, _ in windows)
    required_end = max(date.fromisoformat(following["date"]) - timedelta(days=1) for _, following in windows)
    cursor = date(required_start.year, 1, 1)
    periods = []
    while cursor <= required_end:
        # Keep the small following-year slice separate from the 65 comparison years.
        last_year = min(cursor.year + chunk_years - 1, RECENT["end"]) if cursor.year <= RECENT["end"] else cursor.year
        end = min(date(last_year, 12, 31), required_end)
        periods.append((cursor.isoformat(), end.isoformat()))
        cursor = end + timedelta(days=1)
    return periods


class QuotaBlocked(RuntimeError):
    def __init__(self, reason, resume_at=None, kind="local_budget"):
        super().__init__(reason)
        self.resume_at, self.kind = resume_at, kind


@contextmanager
def batch_lock(data_dir):
    """OS-held lock survives neither a crash nor process exit; no stale PID guessing."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "batch.lock"
    stream = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("已有本项目数据任务正在运行；未发出重复请求。") from None
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


class Budget:
    def __init__(self, data_dir, minute=450, hour=4500, day=9000, month=270000):
        self.path = data_dir / "request_budget.json"
        self.data = read_json(self.path) if self.path.exists() else {"version": 1, "attempts": [], "blocked": None}
        # Migrate an initial pre-release ledger bug: geocoding sidecars describe
        # the same query as their JSON payload; they were never extra requests.
        duplicate_sidecars = [a for a in self.data["attempts"] if str(a.get("source", "")).startswith("raw/geocoding/") and str(a.get("source", "")).endswith(".meta.json")]
        if duplicate_sidecars:
            self.data.setdefault("corrections", []).append({"at": now(), "reason": "移除误计为独立请求的地理编码metadata旁文件；原请求仍计入，预算未提高。", "removed_entries": duplicate_sidecars})
            self.data["attempts"] = [a for a in self.data["attempts"] if a not in duplicate_sidecars]
            if (self.data.get("blocked") or {}).get("kind") == "local_budget":
                self.data["blocked"] = None  # Recalculate from actual retained requests.
        self.limits = [(60, minute), (3600, hour), (86400, day), (31 * 86400, month)]
        known = {a.get("source") for a in self.data["attempts"]}
        for meta_path in (data_dir / "raw").glob("*/*.meta.json"):
            source = str(meta_path.relative_to(data_dir)).replace("\\", "/")
            if source in known:
                continue
            try:
                meta = read_json(meta_path)
                if not meta.get("url", "").startswith(API) or meta.get("budget_id"):
                    continue
                timestamp = datetime.fromisoformat(meta["retrieved_at"]).timestamp()
                cost = estimate_calls(meta["parameters"])
            except (KeyError, ValueError, TypeError):
                continue
            self.data["attempts"].append({"id": "legacy-" + digest(source.encode())[:16], "timestamp": timestamp, "cost": cost, "source": source})
            known.add(source)
        # Geocoding also uses the provider's public service; count each saved query.
        for path in (data_dir / "raw" / "geocoding").glob("*.json"):
            if path.name.endswith(".meta.json"):
                continue
            source = str(path.relative_to(data_dir)).replace("\\", "/")
            if source not in known:
                self.data["attempts"].append({"id": "geo-" + digest(source.encode())[:16], "timestamp": path.stat().st_mtime, "cost": 1.0, "source": source})
                known.add(source)
        self.save()

    def save(self):
        self.data["updated_at"] = now()
        write_json(self.path, self.data)

    def block(self, reason, resume_at, kind):
        self.data["blocked"] = {"at": now(), "reason": reason, "resume_at": resume_at, "kind": kind}
        self.save()

    def reserve(self, cost, city_id, start, end):
        for duration, limit in self.limits:
            if cost >= limit:
                raise QuotaBlocked(f"单片需{cost:.2f}折算调用，无法满足配置的{duration}秒预算{limit}；请减小 --chunk-years 或恢复较大的合法预算。", kind="budget_configuration")
        stamp = time.time()
        blocked = self.data.get("blocked")
        if blocked and blocked.get("resume_at") and stamp < datetime.fromisoformat(blocked["resume_at"]).timestamp():
            raise QuotaBlocked(blocked["reason"], blocked["resume_at"], blocked["kind"])
        self.data["blocked"] = None
        for duration, limit in reversed(self.limits):
            active = sorted((a for a in self.data["attempts"] if a["timestamp"] > stamp - duration), key=lambda a: a["timestamp"])
            used = sum(a["cost"] for a in active)
            if used + cost >= limit:
                remaining = used + cost - limit
                release = stamp
                for attempt in active:
                    remaining -= attempt["cost"]
                    release = attempt["timestamp"] + duration + 2
                    if remaining < 0:
                        break
                resume = datetime.fromtimestamp(release, timezone.utc).isoformat()
                reason = f"保守共享额度保护：{duration}秒窗口已计{used:.2f}折算调用，下片需{cost:.2f}，配置上限{limit}；断点已保存，可于{resume}后续跑。"
                if release - stamp <= 60:
                    print(f"限速等待 {release-stamp:.1f} 秒", flush=True)
                    time.sleep(max(.1, release - stamp))
                    return self.reserve(cost, city_id, start, end)
                self.block(reason, resume, "local_budget")
                raise QuotaBlocked(reason, resume)
        # Smooth the minutely allowance instead of issuing a burst to its edge.
        previous = self.data["attempts"][-1] if self.data["attempts"] else None
        if previous:
            wait = previous["timestamp"] + max(1.0, previous["cost"] * 60 / self.limits[0][1]) - time.time()
            if wait > 0:
                time.sleep(min(wait, 60))
        token = uuid.uuid4().hex
        self.data["attempts"].append({"id": token, "timestamp": time.time(), "cost": cost, "city_id": city_id, "start": start, "end": end})
        self.save()
        return token


def retry_after(value, body):
    stamp = time.time()
    if value:
        try:
            return datetime.fromtimestamp(stamp + max(0, float(value)), timezone.utc).isoformat()
        except ValueError:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
    lowered = body.lower()
    delay = 31 * 86400 if "month" in lowered else 86400 if "day" in lowered or "daily" in lowered else 3600 if "hour" in lowered else 60
    return datetime.fromtimestamp(stamp + delay + 5, timezone.utc).isoformat()


def request_session():
    import requests
    import urllib.request
    session = requests.Session()
    session.headers["User-Agent"] = "Seasonal-Portraits-Local/0.2 (noncommercial research)"
    # Honor the already configured user proxy, never create or rotate one.
    proxies = urllib.request.getproxies()
    if sys.platform == "win32" and not proxies.get("https") and not os.environ.get("HTTPS_PROXY"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                server = winreg.QueryValueEx(key, "ProxyServer")[0]
            if enabled and server:
                pairs = dict(piece.split("=", 1) for piece in server.split(";") if "=" in piece)
                address = (pairs.get("https") or pairs.get("http")) if pairs else server
                if address:
                    proxies["https"] = address if "://" in address else "http://" + address
        except (OSError, ValueError):
            pass
    session.proxies.update({k: v for k, v in proxies.items() if k in ("https", "http")})
    return session


def find_cache(raw_dir, params, verify=True):
    identity = digest(json.dumps({"api": API, "parameters": params}, sort_keys=True).encode())[:16]
    target = raw_dir / f"era5_{params['start_date']}_{params['end_date']}_{identity}.json"
    candidates = [target.with_suffix(".meta.json"), *raw_dir.glob(f"era5_{params['start_date']}_{params['end_date']}_*.meta.json")]
    candidates = sorted((p for p in dict.fromkeys(candidates) if p.is_file()), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for meta_path in candidates:
        if not meta_path.is_file():
            continue
        try:
            meta = read_json(meta_path)
        except (ValueError, UnicodeError):
            if verify:
                raise
            continue
        if meta.get("parameters") != params or not meta.get("url", "").startswith(API + "?") or meta.get("model") != "ERA5":
            continue
        content_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".json"))
        if not content_path.exists():
            continue
        content = content_path.read_bytes()
        if verify and digest(content) != meta.get("sha256"):
            raise ValueError(f"缓存SHA256校验失败，保留原文件供核对：{content_path}")
        return content_path, meta, content
    return target, None, None


class Runner:
    def __init__(self, data_dir, offline=False, refresh=False, chunk_years=5, **budget_limits):
        self.data_dir, self.offline, self.refresh = Path(data_dir), offline, refresh
        self.task_path = self.data_dir / "batch_tasks.json"
        self.tasks = read_json(self.task_path) if self.task_path.exists() else {"schema_version": "1.0", "cities": {}}
        self.budget = Budget(self.data_dir, **budget_limits)
        self.session = None if offline else request_session()
        # The shared astronomical cache is the existing accepted Beijing one.
        legacy.RAW = self.data_dir / "raw"
        self.events, self.astro = legacy.astronomical_windows(offline=offline)
        self.periods = required_periods(self.events, chunk_years)
        write_json(self.data_dir / "provider_policy.json", POLICY)
        for city in get_cities():
            entry = self.tasks["cities"].setdefault(city["id"], {})
            entry.update(city_id=city["id"], name=city["name"], recovery=f".venv\\Scripts\\python.exe scripts\\build_cities.py --city {city['id']}")
            entry.setdefault("status", "not_connected")
            entry.setdefault("stages", {s: "pending" for s in ("acquisition", "validation", "calculation", "publication")})
            entry.setdefault("last_error", None)
            entry.setdefault("retry_count", 0)
            entry.setdefault("last_success", None)
            old = {s["start"] + "/" + s["end"]: s for s in entry.get("slices", [])}
            entry["slices"] = [old.get(a + "/" + b, {"start": a, "end": b, "status": "pending", "attempts": 0}) for a, b in self.periods]
        self.save()

    def save(self):
        self.tasks["updated_at"] = now()
        write_json(self.task_path, self.tasks)

    def chunk(self, city, item):
        import requests
        params = {**parameters(city), "start_date": item["start"], "end_date": item["end"]}
        raw_dir = self.data_dir / "raw" / city["id"]
        path, meta, content = find_cache(raw_dir, params, verify=not self.refresh)
        if content is not None and not self.refresh:
            payload = json.loads(content)
            rows = legacy.validate_chunk(payload, item["start"], item["end"], city["representative_point"])
            item.update(status="cached", cache_file=str(path.relative_to(self.data_dir)).replace("\\", "/"), sha256=meta["sha256"], last_error=None)
            self.save()
            return payload, rows, {**meta, "cache_file": item["cache_file"]}
        if self.offline:
            raise FileNotFoundError(f"离线缓存缺失：{city['name']} {item['start']}—{item['end']}；不使用其他城市替代。")
        entry = self.tasks["cities"][city["id"]]
        for retry in range(3):
            budget_id = self.budget.reserve(estimate_calls(params), city["id"], item["start"], item["end"])
            item.update(status="fetching", attempts=item.get("attempts", 0) + 1)
            entry["current_slice"] = {"start": item["start"], "end": item["end"]}
            self.save()
            print(f"  获取 {city['name']} {item['start']}—{item['end']}，折算{estimate_calls(params):.2f}次", flush=True)
            try:
                response = self.session.get(API, params=params, timeout=(15, 60))
                if response.status_code == 429:
                    reason = f"提供方429共享额度限制：{response.text[:1500]}"
                    resume = retry_after(response.headers.get("Retry-After"), response.text)
                    item.update(status="blocked", last_error=reason, retry_after=response.headers.get("Retry-After"), resume_at=resume)
                    self.budget.block(reason, resume, "provider_429")
                    self.save()
                    raise QuotaBlocked(reason, resume, "provider_429")
                response.raise_for_status()
                content = response.content
                payload = json.loads(content)
                if payload.get("error"):
                    raise ValueError(str(payload))
                rows = legacy.validate_chunk(payload, item["start"], item["end"], city["representative_point"])
                grid = {k: payload.get(k) for k in ("latitude", "longitude", "elevation")}
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in grid.values()):
                    raise ValueError("返回网格或高程不是有效数值")
                raw_dir.mkdir(parents=True, exist_ok=True)
                if path.exists() and digest(path.read_bytes()) != digest(content):
                    # Old report manifests continue to resolve their immutable raw bytes.
                    path = path.with_name(f"{path.stem}-{digest(content)[:16]}.json")
                temp = path.with_suffix(".tmp")
                temp.write_bytes(content)
                temp.replace(path)
                meta = {"retrieved_at": now(), "url": response.url, "parameters": params, "sha256": digest(content), "budget_id": budget_id,
                        "estimated_api_calls": estimate_calls(params), "response_headers": {"content_type": response.headers.get("content-type"), "status": response.status_code},
                        "model": "ERA5", "returned_grid": grid, "fixed_grid_policy": "nearest; elevation=nan disables elevation downscaling"}
                write_json(path.with_suffix(".meta.json"), meta)
                item.update(status="cached", cache_file=str(path.relative_to(self.data_dir)).replace("\\", "/"), sha256=meta["sha256"], last_error=None)
                self.save()
                return payload, rows, {**meta, "cache_file": item["cache_file"]}
            except (requests.RequestException, TimeoutError, OSError) as exc:
                entry["retry_count"] += 1
                item.update(status="failed", last_error=f"{type(exc).__name__}: {exc}")
                self.save()
                # A parameter/auth error cannot improve through repeated identical requests.
                if isinstance(exc, requests.HTTPError) and exc.response is not None and 400 <= exc.response.status_code < 500:
                    raise
                if retry == 2:
                    raise
                time.sleep(3 * 2 ** retry)
        raise RuntimeError("unreachable")

    def build_city(self, city_id, position, total):
        city = get_city(city_id)
        entry = self.tasks["cities"][city_id]
        entry.update(status="preparing", started_at=now(), last_error=None)
        entry["stages"].update(acquisition="running", validation="pending", calculation="pending", publication="pending")
        self.save()
        rows, requests_meta, grids = {}, [], []
        for index, item in enumerate(entry["slices"]):
            payload, chunk, meta = self.chunk(city, item)
            if set(rows).intersection(chunk):
                raise ValueError("时间片重复日期")
            rows.update(chunk)
            requests_meta.append(meta)
            grids.append({key: payload.get(key) for key in ("latitude", "longitude", "elevation")})
            entry["cached_slices"] = index + 1
            print(f"城市{position}/{total}，当前处理{city['name']}，已完成{index+1}/{len(entry['slices'])}个数据片", flush=True)
        entry["stages"].update(acquisition="complete", validation="running")
        self.save()
        if any(grid != grids[0] for grid in grids):
            raise ValueError("跨时间片返回网格或高程不一致，拒绝合并")
        self.validate(city_id, None)  # Ensure publication validator is installed before calculating.
        entry["stages"].update(validation="complete", calculation="running")
        self.save()
        annual = {term["id"]: [] for term in TERMS}
        for event, following in zip(self.events, self.events[1:]):
            if BASELINE["start"] <= event["year"] <= RECENT["end"]:
                annual[event["id"]].append(legacy.aggregate_window(rows, date.fromisoformat(event["date"]), date.fromisoformat(following["date"])))
        terms = [make_term(term, annual[term["id"]]) for term in TERMS]
        report = common_report(terms, False, city_id, city["name"])
        report["city"] = {"id": city_id, "name": city["name"], "region": city["region"], "category": city["category"], "representative_point": city["representative_point"], "grid": grids[0]}
        report["source"] = {"name": "Open-Meteo / ERA5 再分析", "url": POLICY["documentation_url"], "model": "ERA5", "attribution": POLICY["attribution"],
                            "description": "固定ERA5模型的城市代表点历史再分析数据；不是气象站实测。日均降水为节气窗口内日降水总量的平均值。",
                            "license": POLICY["license_url"], "api": API, "request_parameters": parameters(city), "requests_manifest": f"raw/{city_id}/request_manifest.json",
                            "grid_selection": "nearest", "elevation_handling": "elevation=nan; disable downscaling; returned elevation is the ERA5 grid average"}
        report["quality"] = {"complete_terms": sum(term["status"] != "insufficient_data" for term in terms), "date_start": min(rows), "date_end": max(rows), "daily_rows": len(rows), "duplicate_dates": 0, "missing_days": 0,
                             "missing_values": {key: sum(row[key] is None for row in rows.values()) for key in VARIABLES}, "units_checked": True, "grid_consistent": True,
                             "daily_extrema_checked": True, "baseline_requested_years": 30, "recent_requested_years": 30,
                             "valid_years": {term["id"]: {"baseline": term["metrics"][0]["baseline_n"], "recent": term["metrics"][0]["recent_n"]} for term in terms},
                             "sensitive_terms": [term["id"] for term in terms if term["sensitivity"]["sensitive"]], "astronomy": self.astro,
                             "day_approximation": "交节北京时间日期起至下一交节日期前一日，忽略交节日内的小时差异。", "scope": "固定单个代表点；不代表城市内空间差异；不进行原因归因。"}
        manifest_identity = digest(json.dumps(requests_meta, sort_keys=True, ensure_ascii=False).encode())[:16]
        report["source"]["requests_manifest"] = f"raw/{city_id}/manifests/{manifest_identity}.json"
        self.validate(city_id, report)
        entry["stages"].update(calculation="complete", publication="running")
        self.save()
        return self.publish(city_id, report, rows, requests_meta, grids[0])

    def publish(self, city_id, report, rows, requests_meta, grid):
        """Validate and compare first; atomically publish with rollback on write failure."""
        import copy
        entry = self.tasks["cities"][city_id]
        report_path = self.data_dir / "reports" / f"{city_id}.json"
        manifest_path = self.data_dir / "report_manifest.json"
        # Read before mutating anything, so corrupt installation metadata cannot erase a report.
        installed = read_json(manifest_path).get("installed", []) if manifest_path.exists() else []
        if not isinstance(installed, list) or not all(isinstance(value, str) for value in installed):
            raise ValueError("报告安装清单无效；未覆盖现有报告")
        previous = None
        if report_path.exists():
            try:
                previous = read_json(report_path)
                self.validate(city_id, previous)
            except (ValueError, TypeError, KeyError):
                previous = None
        preserve_beijing = city_id == "beijing" and previous is not None
        if preserve_beijing:
            if previous["terms"] != report["terms"] or previous["summary"] != report["summary"] or previous["city"]["grid"] != report["city"]["grid"]:
                write_json(self.data_dir / "candidates" / "beijing-needs-review.json", report)
                raise ValueError("北京复算与认可基线有差异；候选保留供复核，未覆盖报告、原始清单或CSV。")
            report = previous
        raw_dir = self.data_dir / "raw" / city_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        alias = raw_dir / "request_manifest.json"
        csv_path = raw_dir / "daily.csv"
        snapshots = {path: path.read_bytes() if path.exists() else None for path in (report_path, manifest_path, alias, csv_path, self.task_path)}
        old_entry = copy.deepcopy(entry)
        try:
            if not preserve_beijing:
                if report_path.exists():
                    history = report_path.parent / "history"
                    history.mkdir(exist_ok=True)
                    shutil.copy2(report_path, history / f"{city_id}-{digest(report_path.read_bytes())[:16]}.json")
                raw_manifest = {"started_at": entry["started_at"], "completed_at": now(), "requests": requests_meta, "grid": grid}
                version_path = self.data_dir / report["source"]["requests_manifest"]
                # A content-addressed manifest is never replaced with different timestamps.
                if not version_path.exists():
                    write_json(version_path, raw_manifest)
                else:
                    existing_manifest = read_json(version_path)
                    if existing_manifest.get("requests") != requests_meta or existing_manifest.get("grid") != grid:
                        raise ValueError("已存版本化请求清单内容不匹配，拒绝发布指向损坏来源的报告")
                csv_tmp = csv_path.with_suffix(".csv.tmp")
                with csv_tmp.open("w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["date", *VARIABLES])
                    writer.writeheader()
                    writer.writerows({"date": stamp, **row} for stamp, row in sorted(rows.items()))
                csv_tmp.replace(csv_path)
                write_json(alias, raw_manifest)
            write_json(manifest_path, {"installed": sorted(set(installed + [city_id]))})
            if not preserve_beijing:
                write_json(report_path, report)
            entry.update(status="ready", last_error=None, completed_at=now(), current_slice=None,
                         last_success={"report_id": report["report_id"], "generated_at": report["generated_at"], "sha256": digest(report_path.read_bytes()), "verified_at": now()})
            entry["stages"].update(publication="complete")
            self.save()
        except BaseException:
            entry.clear()
            entry.update(old_entry)
            for path, content in reversed(list(snapshots.items())):
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    temporary = path.with_suffix(path.suffix + ".rollback.tmp")
                    temporary.write_bytes(content)
                    temporary.replace(path)
            raise
        print(report["summary"], flush=True)
        return report

    @staticmethod
    def validate(city_id, report):
        from scripts.report_validation import validate_report
        if report is not None:
            validate_report(report, city_id)

    def run(self, city_ids, resume=False):
        blocked = None
        failed = []
        for index, city_id in enumerate(city_ids, 1):
            entry = self.tasks["cities"][city_id]
            path = self.data_dir / "reports" / f"{city_id}.json"
            if resume and path.exists():
                try:
                    self.validate(city_id, read_json(path))
                    if entry["status"] in ("ready", "not_connected"):
                        entry.update(status="ready", last_error=None, last_success={"report_id": read_json(path)["report_id"], "sha256": digest(path.read_bytes()), "verified_at": now()})
                        self.save()
                        print(f"复用已校验报告：{get_city(city_id)['name']}", flush=True)
                        continue
                except (ValueError, TypeError, KeyError):
                    pass
            # With a quota stop, cache-complete cities still calculate without requests.
            before_offline = self.offline
            if blocked:
                self.offline = True
            try:
                self.build_city(city_id, index, len(city_ids))
            except QuotaBlocked as exc:
                blocked = exc
                entry.update(status="acquisition_blocked", last_error=str(exc), resume_at=exc.resume_at, block_kind=exc.kind)
                entry["stages"]["acquisition"] = "blocked"
                self.tasks["shared_blocker"] = {"reason": str(exc), "resume_at": exc.resume_at, "kind": exc.kind}
                self.save()
                print(str(exc), flush=True)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                if blocked and isinstance(exc, FileNotFoundError):
                    reason = str(blocked)
                    entry.update(status="acquisition_blocked", last_error=str(blocked), resume_at=blocked.resume_at, block_kind=blocked.kind)
                    entry["stages"]["acquisition"] = "blocked"
                else:
                    entry.update(status="acquisition_blocked" if isinstance(exc, (OSError, FileNotFoundError)) or "requests" in type(exc).__module__ else "invalid_report", last_error=reason)
                    failed.append(city_id)
                for stage, state in entry["stages"].items():
                    if state == "running":
                        entry["stages"][stage] = "failed"
                self.save()
                print(f"{get_city(city_id)['name']} 未发布：{reason}", flush=True)
            finally:
                self.offline = before_offline
        self.tasks["last_run"] = {"completed_at": now(), "requested": city_ids, "failed": failed, "blocked": bool(blocked)}
        if not blocked:
            budget_block = self.budget.data.get("blocked") if hasattr(self, "budget") else None
            if budget_block and budget_block.get("resume_at") and datetime.fromisoformat(budget_block["resume_at"]).timestamp() > time.time():
                self.tasks["shared_blocker"] = budget_block
            else:
                self.tasks.pop("shared_blocker", None)
        self.save()
        return 2 if blocked or failed else 0


def check_reports(data_dir, city_ids):
    from scripts.report_validation import validate_report
    results = []
    for city_id in city_ids:
        path = data_dir / "reports" / f"{city_id}.json"
        try:
            report = read_json(path)
            validate_report(report, city_id)
            result = {"city_id": city_id, "name": get_city(city_id)["name"], "status": "ready", "terms": len(report["terms"]), "sha256": digest(path.read_bytes())}
        except Exception as exc:
            result = {"city_id": city_id, "name": get_city(city_id)["name"], "status": "missing" if not path.exists() else "invalid", "reason": str(exc)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    write_json(data_dir / "report_check.json", {"checked_at": now(), "ready": sum(r["status"] == "ready" for r in results), "total": len(results), "cities": results})
    return 0 if all(r["status"] == "ready" for r in results) else 2


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", action="append", help="城市id，可重复或逗号分隔")
    parser.add_argument("--all", action="store_true", help="按阶段B优先次序获取全部城市")
    parser.add_argument("--resume", action="store_true", help="复用有效报告，续跑未完成任务")
    parser.add_argument("--offline", action="store_true", help="禁止网络，只用已校验原始缓存复算")
    parser.add_argument("--refresh", action="store_true", help="显式重取所选城市，保留旧缓存/报告版本")
    parser.add_argument("--check", action="store_true", help="只检查已发布报告，不联网")
    parser.add_argument("--chunk-years", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--minute-budget", type=float, default=450)
    parser.add_argument("--hour-budget", type=float, default=4500)
    parser.add_argument("--day-budget", type=float, default=9000)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="仅用于独立测试或迁移；正常使用默认目录")
    args = parser.parse_args(argv)
    if args.offline and args.refresh:
        parser.error("--offline与--refresh互斥")
    if not (0 < args.minute_budget < 600 and 0 < args.hour_budget < 5000 and 0 < args.day_budget < 10000):
        parser.error("预算必须为正且低于提供方600/分钟、5000/小时、10000/日限额")
    all_ids = [city["id"] for city in get_cities()]
    selected = list(dict.fromkeys(part for value in args.city or [] for part in value.split(",")))
    if not selected:
        selected = PRIORITY + [city_id for city_id in all_ids if city_id not in PRIORITY]
    if any(city_id not in all_ids for city_id in selected):
        parser.error("存在未注册城市id")
    try:
        with batch_lock(args.data_dir):
            if args.check:
                return check_reports(args.data_dir, selected)
            runner = Runner(args.data_dir, args.offline, args.refresh, args.chunk_years,
                            minute=args.minute_budget, hour=args.hour_budget, day=args.day_budget)
            return runner.run(selected, args.resume)
    except KeyboardInterrupt:
        print("任务已中断；已完成的片段和原报告保留，下次使用 --resume。", flush=True)
        return 130
    except Exception as exc:
        print(f"未启动/完成数据任务：{type(exc).__name__}: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
