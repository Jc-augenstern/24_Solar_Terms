"""Offline safety checks for the resumable downloader. No provider calls."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_cities import (API, Budget, QuotaBlocked, Runner, batch_lock,
                                 digest, estimate_calls, find_cache, parameters,
                                 required_periods, retry_after)
from scripts.city_registry import get_city


def test_calendar_derived_boundary_and_legacy_chunk_reuse():
    calendar = json.loads((ROOT / "data/raw/astronomy/solar_terms_1961_2026.json").read_text(encoding="utf-8"))
    events = calendar["events"]
    periods = required_periods(events)
    assert periods[0] == ("1961-01-01", "1965-12-31")
    assert periods[-1] == ("2026-01-01", "2026-01-04")
    # The cross-year bound comes from the calendar, not a copied Beijing end date.
    altered = [dict(event) for event in events]
    next(event for event in altered if event["year"] == 2026 and event["id"] == "xiaohan")["date"] = "2026-01-06"
    assert required_periods(altered)[-1][1] == "2026-01-05"
    params = {**parameters(get_city("beijing")), "start_date": periods[0][0], "end_date": periods[0][1]}
    path, meta, content = find_cache(ROOT / "data/raw/beijing", params)
    assert content and meta["sha256"] == digest(content)
    assert path.name.endswith("e5687ca4d911.json")
    wrong = {**params, "latitude": get_city("harbin")["representative_point"]["latitude"]}
    assert find_cache(ROOT / "data/raw/beijing", wrong)[2] is None


def test_fractional_calls_and_persisted_rolling_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_cities.time.sleep", lambda _: None)
    params = {"start_date": "2000-01-01", "end_date": "2000-01-28", "daily": ",".join(f"v{i}" for i in range(15))}
    assert estimate_calls(params) == 3
    params["daily"] = "a,b,c,d"
    params["end_date"] = "2004-12-31"
    assert estimate_calls(params) > 130
    budget = Budget(tmp_path, minute=450, hour=4500, day=140)
    budget.reserve(130, "test", "2000-01-01", "2004-12-31")
    restarted = Budget(tmp_path, minute=450, hour=4500, day=140)
    with pytest.raises(QuotaBlocked) as error:
        restarted.reserve(130, "test2", "2000-01-01", "2004-12-31")
    assert error.value.resume_at and error.value.kind == "local_budget"
    assert len(restarted.data["attempts"]) == 1  # A blocked request was never sent/reserved.


def test_cache_hash_is_checked_but_explicit_refresh_can_repair(tmp_path):
    params = {**parameters(get_city("beijing")), "start_date": "1961-01-01", "end_date": "1965-12-31"}
    path, _, _ = find_cache(tmp_path, params)
    path.write_bytes(b"corrupt")
    meta = {"parameters": params, "url": API + "?test=1", "model": "ERA5", "sha256": "bad"}
    path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        find_cache(tmp_path, params)
    assert find_cache(tmp_path, params, verify=False)[2] == b"corrupt"


def test_exclusive_batch_lock_releases_after_failure(tmp_path):
    with batch_lock(tmp_path):
        with pytest.raises(RuntimeError, match="已有"):
            with batch_lock(tmp_path):
                raise AssertionError("second writer entered")
    with batch_lock(tmp_path):
        pass


def test_retry_after_seconds_http_date_and_limit_message():
    before = time.time()
    assert datetime.fromisoformat(retry_after("120", "")).timestamp() >= before + 120
    assert retry_after("Thu, 29 Oct 2026 14:00:00 GMT", "") == "2026-10-29T14:00:00+00:00"
    assert datetime.fromisoformat(retry_after(None, "Daily API request limit exceeded")).timestamp() >= before + 86400
    assert datetime.fromisoformat(retry_after(None, "Monthly API request limit exceeded")).timestamp() >= before + 31 * 86400


def test_single_slice_larger_than_budget_stops_without_sleep(tmp_path, monkeypatch):
    def no_sleep(_):
        raise AssertionError("configuration problem must not wait")
    monkeypatch.setattr("scripts.build_cities.time.sleep", no_sleep)
    budget = Budget(tmp_path, minute=10)
    with pytest.raises(QuotaBlocked, match="chunk-years") as exc:
        budget.reserve(130, "test", "1961-01-01", "1965-12-31")
    assert exc.value.kind == "budget_configuration"
    assert not budget.data["attempts"]


def test_429_stops_globally_and_never_turns_failure_into_scientific_missing(tmp_path):
    class Response:
        status_code = 429
        text = '{"error":true,"reason":"Daily API request limit exceeded"}'
        headers = {"Retry-After": "3600"}
    class Session:
        calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response()
    runner = Runner.__new__(Runner)
    runner.data_dir, runner.offline, runner.refresh = tmp_path, False, False
    runner.task_path = tmp_path / "batch_tasks.json"
    runner.budget = Budget(tmp_path)
    runner.session = Session()
    runner.tasks = {"cities": {"harbin": {"retry_count": 0, "stages": {}, "slices": []}}}
    item = {"start": "1961-01-01", "end": "1965-12-31", "attempts": 0}
    runner.tasks["cities"]["harbin"]["slices"] = [item]
    with pytest.raises(QuotaBlocked) as error:
        runner.chunk(get_city("harbin"), item)
    assert error.value.kind == "provider_429"
    assert runner.session.calls == 1
    assert item["status"] == "blocked"
    assert not (tmp_path / "reports/harbin.json").exists()
    with pytest.raises(QuotaBlocked):
        runner.budget.reserve(1, "xian", "2000-01-01", "2000-01-01")
    assert runner.session.calls == 1


def test_download_failure_preserves_old_report(tmp_path):
    runner = Runner.__new__(Runner)
    runner.data_dir, runner.offline = tmp_path, False
    runner.task_path = tmp_path / "batch_tasks.json"
    runner.tasks = {"cities": {"harbin": {"status": "ready", "stages": {}, "last_success": {"report_id": "old-valid"}}}}
    path = tmp_path / "reports/harbin.json"
    path.parent.mkdir()
    original = b'{"previous":"valid cached report placeholder"}'
    path.write_bytes(original)
    def fail(*args):
        raise OSError("connection timeout")
    runner.build_city = fail
    assert runner.run(["harbin"]) == 2
    assert path.read_bytes() == original
    assert runner.tasks["cities"]["harbin"]["status"] == "acquisition_blocked"
    assert runner.tasks["cities"]["harbin"]["last_success"] == {"report_id": "old-valid"}


def test_offline_missing_cache_cannot_call_network(tmp_path):
    runner = Runner.__new__(Runner)
    runner.data_dir, runner.offline, runner.refresh = tmp_path, True, False
    runner.session = None
    with pytest.raises(FileNotFoundError, match="离线缓存缺失"):
        runner.chunk(get_city("harbin"), {"start": "1961-01-01", "end": "1965-12-31"})


def publication_runner(tmp_path, city_id):
    runner = Runner.__new__(Runner)
    runner.data_dir = tmp_path
    runner.task_path = tmp_path / "batch_tasks.json"
    runner.tasks = {"cities": {city_id: {"started_at": "test", "status": "preparing", "stages": {"publication": "running"}}}}
    runner.validate = lambda *args: None
    runner.save()
    (tmp_path / "reports").mkdir()
    (tmp_path / "raw" / city_id).mkdir(parents=True)
    (tmp_path / "report_manifest.json").write_text('{"installed": ["beijing"]}', encoding="utf-8")
    return runner


def test_publication_failure_rolls_back_old_report_and_metadata(tmp_path, monkeypatch):
    import scripts.build_cities as module
    runner = publication_runner(tmp_path, "harbin")
    report_path = tmp_path / "reports/harbin.json"
    report_path.write_text('{"old":"valid"}', encoding="utf-8")
    task_before = runner.task_path.read_bytes()
    manifest_before = (tmp_path / "report_manifest.json").read_bytes()
    report = {"report_id": "new", "generated_at": "test", "summary": "new", "source": {"requests_manifest": "raw/harbin/manifests/test.json"}}
    def fail_final_status():
        raise OSError("disk write failed after report publication")
    runner.save = fail_final_status
    with pytest.raises(OSError):
        runner.publish("harbin", report, {}, [], {})
    assert report_path.read_text() == '{"old":"valid"}'
    assert runner.task_path.read_bytes() == task_before
    assert (tmp_path / "report_manifest.json").read_bytes() == manifest_before
    assert not (tmp_path / "raw/harbin/daily.csv").exists()


def test_beijing_candidate_rejection_keeps_report_manifest_and_csv(tmp_path):
    runner = publication_runner(tmp_path, "beijing")
    old = {"terms": [{"score": 1}], "summary": "old", "city": {"grid": {"latitude": 40}}}
    report_path = tmp_path / "reports/beijing.json"
    report_path.write_text(json.dumps(old), encoding="utf-8")
    manifest = tmp_path / "raw/beijing/request_manifest.json"
    daily = tmp_path / "raw/beijing/daily.csv"
    manifest.write_text("original provenance", encoding="utf-8")
    daily.write_text("original daily values", encoding="utf-8")
    new = {**old, "summary": "changed"}
    with pytest.raises(ValueError, match="北京复算"):
        runner.publish("beijing", new, {}, [], {})
    assert json.loads(report_path.read_text()) == old
    assert manifest.read_text() == "original provenance"
    assert daily.read_text() == "original daily values"


def test_corrupt_previous_report_can_be_repaired_and_is_preserved(tmp_path):
    runner = publication_runner(tmp_path, "harbin")
    report_path = tmp_path / "reports/harbin.json"
    report_path.write_bytes(b"broken json")
    new = {"report_id": "valid", "generated_at": "test", "summary": "repaired", "source": {"requests_manifest": "raw/harbin/manifests/test.json"}}
    runner.publish("harbin", new, {}, [], {})
    assert json.loads(report_path.read_text()) == new
    assert any(path.read_bytes() == b"broken json" for path in (tmp_path / "reports/history").iterdir())


def test_refresh_writes_immutable_new_raw_path(tmp_path):
    runner = Runner.__new__(Runner)
    runner.data_dir, runner.offline, runner.refresh = tmp_path, False, True
    runner.task_path = tmp_path / "batch_tasks.json"
    runner.budget = Budget(tmp_path)
    city = get_city("harbin")
    item = {"start": "2000-01-01", "end": "2000-01-01", "attempts": 0}
    runner.tasks = {"cities": {"harbin": {"retry_count": 0, "slices": [item]}}}
    params = {**parameters(city), "start_date": item["start"], "end_date": item["end"]}
    directory = tmp_path / "raw/harbin"
    directory.mkdir(parents=True)
    path, _, _ = find_cache(directory, params)
    old = b"old response being repaired"
    path.write_bytes(old)
    path.with_suffix(".meta.json").write_text(json.dumps({"parameters": params, "url": API + "?test=1", "model": "ERA5", "sha256": digest(old)}), encoding="utf-8")
    payload = {"latitude": city["representative_point"]["latitude"], "longitude": city["representative_point"]["longitude"], "elevation": 150,
               "timezone": "Asia/Shanghai", "utc_offset_seconds": 28800,
               "daily_units": {"temperature_2m_mean": "°C", "temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"},
               "daily": {"time": ["2000-01-01"], "temperature_2m_mean": [1], "temperature_2m_max": [2], "temperature_2m_min": [-2], "precipitation_sum": [0]}}
    content = json.dumps(payload).encode()
    class Response:
        status_code, headers, url = 200, {"content-type": "application/json"}, API + "?test=1"
        def raise_for_status(self):
            pass
    response = Response()
    response.content = content
    class Session:
        def get(self, *args, **kwargs):
            return response
    runner.session = Session()
    result, rows, meta = runner.chunk(city, item)
    assert path.read_bytes() == old
    new_path = tmp_path / meta["cache_file"]
    assert new_path != path and new_path.read_bytes() == content
    assert find_cache(directory, params)[0] == new_path


def test_raw_boolean_is_rejected_instead_of_becoming_zero():
    from scripts.build_beijing import validate_chunk
    payload = {"latitude": 39.9, "longitude": 116.4, "timezone": "Asia/Shanghai", "utc_offset_seconds": 28800,
               "daily_units": {"temperature_2m_mean": "°C", "temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"},
               "daily": {"time": ["2000-01-01"], "temperature_2m_mean": [False], "temperature_2m_max": [2], "temperature_2m_min": [-2], "precipitation_sum": [0]}}
    with pytest.raises(ValueError, match="非法数值"):
        validate_chunk(payload, "2000-01-01", "2000-01-01")
