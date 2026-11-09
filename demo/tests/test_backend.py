"""Isolated API tests. Never write to the delivered tribute database."""
import copy
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import create_app


@pytest.fixture
def museum(tmp_path):
    data = tmp_path / "data"
    (data / "reports").mkdir(parents=True)
    (data / "methodology").mkdir()
    sample = json.loads((ROOT / "data/reports/demo.json").read_text(encoding="utf-8"))
    (data / "reports/demo.json").write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    (data / "methodology/v0.1.json").write_text('{"version":"v0.1"}', encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>local test</title>", encoding="utf-8")
    db = data / "test.sqlite3"
    return data, db, dist, TestClient(create_app(data, db, dist)), sample


def tribute(term_id="lichun", action="light", experience="test-experience-01", key=None):
    return {"experience_id": experience, "term_id": term_id, "action": action, "idempotency_key": key or str(uuid4())}


def test_duplicate_retry_and_persistence(museum):
    data, db, dist, client, _ = museum
    endpoint = "/api/v1/cities/demo/tributes"
    assert client.get(endpoint).json()["total"] == 0
    body = tribute()
    assert client.post(endpoint, json=body).json()["recorded_now"] is True
    assert client.post(endpoint, json=body).json()["recorded_now"] is False
    body["idempotency_key"] = str(uuid4())
    assert client.post(endpoint, json=body).json()["total"] == 1
    restarted = TestClient(create_app(data, db, dist))
    saved = restarted.get(endpoint, params={"experience_id": body["experience_id"]}).json()
    assert saved["total"] == saved["light"] == 1
    assert saved["flower"] == 0
    assert saved["recorded"] == [{"term_id": "lichun", "action": "light"}]
    assert restarted.post(endpoint, json=tribute(action="flower")).json()["total"] == 2


def test_concurrent_natural_key_and_idempotency_conflict(museum):
    _, _, _, client, _ = museum
    endpoint = "/api/v1/cities/demo/tributes"
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda _: client.post(endpoint, json=tribute()), range(12)))
    assert all(r.status_code == 200 for r in replies)
    assert sum(r.json()["recorded_now"] for r in replies) == 1
    body = tribute(action="flower")
    assert client.post(endpoint, json=body).status_code == 200
    body["action"] = "light"
    response = client.post(endpoint, json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert client.get(endpoint).json()["total"] == 2


def test_mode_isolation_and_insufficient_archive(museum):
    data, _, _, client, sample = museum
    # Real Beijing and the explicit demo are copied only into the temporary test folder.
    real_fixture = json.loads((ROOT / "data/reports/beijing.json").read_text(encoding="utf-8"))
    (data / "reports/beijing.json").write_text(json.dumps(real_fixture, ensure_ascii=False), encoding="utf-8")
    body = tribute()
    assert client.post("/api/v1/cities/demo/tributes", json=body).json()["total"] == 1
    assert client.get("/api/v1/cities/beijing/tributes").json()["total"] == 0
    body["idempotency_key"] = str(uuid4())
    assert client.post("/api/v1/cities/beijing/tributes", json=body).json()["total"] == 1
    assert client.get("/api/v1/cities/demo/tributes").json()["total"] == 1
    insufficient = next(t for t in sample["terms"] if t["status"] == "insufficient_data")
    report = client.get("/api/v1/cities/demo/report").json()
    assert next(t for t in report["terms"] if t["id"] == insufficient["id"])["score"] is None
    assert client.post("/api/v1/cities/demo/tributes", json=tribute(term_id=insufficient["id"])).status_code == 200


def test_unconnected_missing_and_corrupt_reports(museum):
    data, _, _, client, sample = museum
    assert client.get("/api/v1/cities/unknown/report").status_code == 404
    response = client.get("/api/v1/cities/shanghai/report")
    assert response.status_code == 503 and response.json()["detail"]["code"] == "not_connected"
    assert client.get("/api/v1/cities/beijing/report").json()["detail"]["code"] == "not_connected"
    (data / "report_manifest.json").write_text('{"installed":["demo","beijing"]}')
    assert client.get("/api/v1/cities/beijing/report").json()["detail"]["code"] == "report_missing"
    (data / "reports/demo.json").write_text("{broken", encoding="utf-8")
    assert client.get("/api/v1/cities/demo/report").json()["detail"]["code"] == "report_parse_failed"
    sample["terms"][0]["score"] = float("nan")
    (data / "reports/demo.json").write_text(json.dumps(sample), encoding="utf-8")
    assert client.get("/api/v1/cities/demo/report").status_code == 500


def test_storage_failure_no_false_success(museum):
    _, db, _, client, _ = museum
    endpoint = "/api/v1/cities/demo/tributes"
    assert client.get(endpoint).json()["total"] == 0
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON tributes BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END")
    response = client.post(endpoint, json=tribute())
    assert response.status_code == 503 and response.json()["detail"]["code"] == "storage_failed"
    assert client.get(endpoint).json()["total"] == 0


def test_validation_local_only_and_shutdown_token(museum):
    _, _, _, client, _ = museum
    endpoint = "/api/v1/cities/demo/tributes"
    assert client.post(endpoint, json=tribute(term_id="not-a-term")).status_code == 404
    assert client.post(endpoint, json=tribute(action="invalid")).status_code == 422
    assert client.post(endpoint, json=tribute(), headers={"Origin": "https://external.example"}).status_code == 403
    assert client.post("/api/internal/shutdown").status_code == 403
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/").status_code == 200
    assert client.get("/api/typo").status_code == 404
    assert client.get("/missing.js").status_code == 404
    assert "connect-src 'self'" in client.get("/").headers["Content-Security-Policy"]


def test_real_beijing_report_and_precise_failure_categories(museum):
    data, _, _, client, _ = museum
    path = data / "reports/beijing.json"
    original = (ROOT / "data/reports/beijing.json").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    (data / "report_manifest.json").write_text('{"installed":["demo","beijing"]}')
    endpoint = "/api/v1/cities/beijing/report"
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json()["is_demo"] is False
    assert len(response.json()["terms"]) == 24
    assert client.get("/").headers["Cache-Control"] == "no-store"
    path.unlink()  # Only pytest's temporary copy, never the real report.
    missing = client.get(endpoint).json()["detail"]
    assert missing["code"] == "report_missing" and "北京报告文件缺失" in missing["message"]
    path.write_text("{bad json", encoding="utf-8")
    broken = client.get(endpoint).json()["detail"]
    assert broken["code"] == "report_parse_failed" and "北京报告解析失败" in broken["message"]
    body = json.loads(original)
    del body["terms"][0]["metrics"]
    path.write_text(json.dumps(body), encoding="utf-8")
    incompatible = client.get(endpoint).json()["detail"]
    assert incompatible["code"] == "report_schema_mismatch"
    cities = client.get("/api/v1/cities").json()["cities"]
    assert next(c for c in cities if c["id"] == "beijing")["data_status"] == "invalid_report"
