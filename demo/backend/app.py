from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from scripts.city_registry import get_cities, get_city
from scripts.report_validation import validate_report

ROOT = Path(__file__).resolve().parents[1]
CITIES = {city["id"]: city["name"] for city in get_cities()}
Identifier = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class Tribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experience_id: Identifier
    term_id: Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z0-9_-]+$")]
    action: Literal["light", "flower"]
    idempotency_key: Identifier


def fail(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite value")
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)


def read_json(path: Path):
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    finite_tree(value)
    return value


def create_app(data_dir: Path | None = None, db_path: Path | None = None, dist_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("DEMO_DATA_DIR", ROOT / "data")).resolve()
    db_path = Path(db_path or os.environ.get("DEMO_DB_PATH", data_dir / "tributes.sqlite3")).resolve()
    dist_dir = Path(dist_dir or ROOT / "frontend" / "dist").resolve()
    app = FastAPI(title="节气讣告本机服务", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.state.shutdown_token = None
    app.state.shutdown_callback = None
    app.state.instance_id = secrets.token_hex(16)

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin != expected:
                return JSONResponse({"detail": {"code": "origin_rejected", "message": "只接受本机作品页面提交。"}}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/") or request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def known(city_id: str):
        if city_id not in CITIES and city_id != "demo":
            fail(404, "unknown_city", "未收录该城市；请选择页面中的34座城市或独立样例。")

    def expected_report(city_id: str) -> bool:
        if city_id == "demo":
            return True
        manifest = data_dir / "report_manifest.json"
        if manifest.exists():
            try:
                return city_id in read_json(manifest).get("installed", [])
            except (ValueError, OSError, AttributeError):
                return True  # A damaged manifest must not silently mean never installed.
        return False

    def task_state(city_id: str) -> dict:
        path = data_dir / "batch_tasks.json"
        if path.is_file():
            try:
                return read_json(path).get("cities", {}).get(city_id, {})
            except (OSError, ValueError, AttributeError, TypeError):
                return {"status": "failed", "last_error": "批量任务记录无法读取，请运行检查城市数据。"}
        return {}

    def preparation_status(city_id: str) -> tuple[str, str]:
        task = task_state(city_id)
        state = task.get("status", "pending")
        detail = str(task.get("last_error") or task.get("reason") or "")[:2000]
        if state in ("blocked", "quota_blocked", "acquisition_blocked", "failed", "download_failed"):
            return "acquisition_blocked", f"{CITIES[city_id]}数据获取受阻。{detail} 可运行“继续未完成城市”；这不是节气评级中的资料不足。"
        if state in ("running", "fetching", "downloading", "validating", "computing", "publishing", "preparing"):
            return "preparing", f"{CITIES[city_id]}数据准备中。{detail} 校验发布完成后提供真实报告。"
        if state in ("invalid_report", "validation_failed"):
            return "invalid_report", f"{CITIES[city_id]}报告校验失败。{detail} 上一份有效报告不会被空报告覆盖。"
        return "not_connected", f"{CITIES[city_id]}尚未完成真实数据接入，请运行“更新全部城市数据”或“继续未完成城市”。这不是节气评级中的资料不足。"

    def load_report(city_id: str) -> dict:
        known(city_id)
        city_name = "样例城" if city_id == "demo" else CITIES[city_id]
        path = data_dir / "reports" / f"{city_id}.json"
        if not path.is_file():
            if expected_report(city_id):
                fail(404, "report_missing", f"{city_name}报告文件缺失，请恢复 data/reports/{city_id}.json 或运行对应生成脚本。")
            status, reason = preparation_status(city_id)
            fail(503, status, reason)
        try:
            raw = read_json(path)
        except FileNotFoundError:
            fail(404, "report_missing", f"{city_name}报告文件缺失，请恢复 data/reports/{city_id}.json。")
        except (ValueError, UnicodeError):
            fail(500, "report_parse_failed", f"{city_name}报告解析失败：文件不是有效的 UTF-8 JSON 或包含非法数值。请恢复原文件或重新计算。")
        except OSError:
            fail(500, "report_unreadable", f"{city_name}报告文件无法读取，请检查文件权限；本机服务仍在运行。")
        try:
            return validate_report(raw, city_id)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ValidationError):
            fail(500, "report_schema_mismatch", f"{city_name}报告字段或评级状态与当前版本不兼容，请恢复原报告或重新计算；不会替换成演示数据。")

    def connect():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tributes (
                    id INTEGER PRIMARY KEY, city_id TEXT NOT NULL, is_demo INTEGER NOT NULL,
                    experience_id TEXT NOT NULL, term_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('light','flower')),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    UNIQUE(city_id,is_demo,experience_id,term_id,action)
                );
                CREATE TABLE IF NOT EXISTS request_keys (
                    idempotency_key TEXT PRIMARY KEY, tribute_id INTEGER NOT NULL REFERENCES tributes(id)
                );
            """)
            return conn
        except Exception:
            conn.close()
            raise

    def counts(conn, city_id: str, is_demo: bool, experience_id: str | None):
        result = {"total": 0, "light": 0, "flower": 0, "terms": {}, "recorded": []}
        rows = conn.execute("SELECT term_id,action,COUNT(*) AS n FROM tributes WHERE city_id=? AND is_demo=? GROUP BY term_id,action", (city_id, int(is_demo)))
        for row in rows:
            result["total"] += row["n"]
            result[row["action"]] += row["n"]
            result["terms"].setdefault(row["term_id"], {"light": 0, "flower": 0})[row["action"]] = row["n"]
        if experience_id:
            result["recorded"] = [dict(row) for row in conn.execute("SELECT term_id,action FROM tributes WHERE city_id=? AND is_demo=? AND experience_id=? ORDER BY id", (city_id, int(is_demo), experience_id))]
        return result

    @app.get("/api/health")
    def health():
        return {"ok": True, "instance_id": app.state.instance_id}

    @app.get("/api/v1/cities")
    def cities():
        entries = []
        for city_id, name in CITIES.items():
            try:
                load_report(city_id)
                status, reason = "ready", "已接入 ERA5 真实再分析报告"
            except HTTPException as exc:
                status, reason = exc.detail["code"], exc.detail["message"]
                if status in ("report_parse_failed", "report_schema_mismatch", "report_unreadable"):
                    status = "invalid_report"
            task = task_state(city_id)
            if status == "ready" and task.get("status") in ("blocked", "failed", "invalid_report", "validation_failed", "quota_blocked", "acquisition_blocked"):
                reason += "；最近更新未完成，继续使用上一份有效报告。" + str(task.get("last_error") or task.get("reason") or "")[:500]
            entries.append({**get_city(city_id), "data_status": status, "reason": reason,
                            "update_status": task.get("status"), "last_success_report": task.get("last_success"), "update_reason": task.get("last_error")})
        try:
            load_report("demo")
            demo_status, demo_reason = "demo", "演示样例，非真实气候结论"
        except HTTPException as exc:
            demo_status, demo_reason = exc.detail["code"], exc.detail["message"]
            if demo_status in ("report_parse_failed", "report_schema_mismatch", "report_unreadable"):
                demo_status = "invalid_report"
        return {"cities": entries, "demo": {"id": "demo", "name": "样例城", "data_status": demo_status, "reason": demo_reason}}

    @app.get("/api/v1/cities/{city_id}/report")
    def report(city_id: str):
        return load_report(city_id)

    @app.get("/api/v1/methodology/{version}")
    def methodology(version: str):
        if version != "v0.1":
            fail(404, "unknown_method", "未收录该方法版本。")
        path = data_dir / "methodology" / "v0.1.json"
        if not path.is_file():
            fail(404, "method_missing", "本地方法说明缺失，请恢复 data/methodology/v0.1.json。")
        try:
            return read_json(path)
        except (OSError, ValueError):
            fail(500, "invalid_method", "本地方法说明无法读取，请恢复原文件。")

    @app.get("/api/v1/cities/{city_id}/tributes")
    def get_tributes(city_id: str, experience_id: Identifier | None = Query(default=None)):
        report = load_report(city_id)
        try:
            conn = connect()
            try:
                return counts(conn, city_id, report["is_demo"], experience_id)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            fail(503, "storage_failed", "本机纪念数据库无法读取。请检查 data 目录权限或磁盘空间后重试；没有返回虚构计数。")

    @app.post("/api/v1/cities/{city_id}/tributes")
    def post_tribute(city_id: str, body: Tribute):
        report = load_report(city_id)
        if body.term_id not in {term["id"] for term in report["terms"]}:
            fail(404, "unknown_term", "报告中不存在该节气，纪念未记录。")
        natural = (city_id, int(report["is_demo"]), body.experience_id, body.term_id, body.action)
        try:
            conn = connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                previous = conn.execute("SELECT t.* FROM request_keys k JOIN tributes t ON t.id=k.tribute_id WHERE k.idempotency_key=?", (body.idempotency_key,)).fetchone()
                recorded_now = False
                if previous:
                    prior = tuple(previous[key] for key in ("city_id", "is_demo", "experience_id", "term_id", "action"))
                    if prior != natural:
                        fail(409, "idempotency_conflict", "该请求标识已用于不同操作，本次未记录。请刷新后重试。")
                else:
                    cursor = conn.execute("INSERT OR IGNORE INTO tributes(city_id,is_demo,experience_id,term_id,action) VALUES(?,?,?,?,?)", natural)
                    recorded_now = cursor.rowcount == 1
                    row = conn.execute("SELECT id FROM tributes WHERE city_id=? AND is_demo=? AND experience_id=? AND term_id=? AND action=?", natural).fetchone()
                    conn.execute("INSERT INTO request_keys(idempotency_key,tribute_id) VALUES(?,?)", (body.idempotency_key, row["id"]))
                result = counts(conn, city_id, report["is_demo"], body.experience_id)
                conn.commit()
                return {**result, "recorded_now": recorded_now}
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            fail(503, "storage_failed", "纪念未能保存到本机数据库。请检查 data 目录权限或磁盘空间后重试；不会显示成功。")

    @app.post("/api/internal/shutdown")
    def shutdown(x_shutdown_token: str = Header(default="")):
        token = app.state.shutdown_token
        if not token or not secrets.compare_digest(x_shutdown_token, token):
            fail(403, "invalid_shutdown_token", "仅本项目启动器可关闭当前服务。")
        if app.state.shutdown_callback:
            app.state.shutdown_callback()
        return {"ok": True}

    @app.get("/{asset_path:path}")
    def static(asset_path: str):
        if asset_path.startswith("api/"):
            fail(404, "unknown_endpoint", "本机接口不存在。")
        target = (dist_dir / (asset_path or "index.html")).resolve()
        if not target.is_relative_to(dist_dir):
            fail(404, "asset_missing", "资源不存在。")
        if target.is_file():
            return FileResponse(target)
        if not asset_path and not (dist_dir / "index.html").exists():
            fail(503, "frontend_missing", "前端尚未构建，请先运行“首次准备”。")
        fail(404, "asset_missing", "本地页面资源缺失，请重新构建前端。")

    return app
