"""Windows/local launcher: no dependency installation or data fetching at startup."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("DEMO_STATE_DIR", ROOT / "data" / "runtime"))
STATE_FILE = STATE_DIR / "server.json"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call_local(url, *, token=None):
    req = urllib.request.Request(url, data=b"" if token else None, headers={"X-Shutdown-Token": token} if token else {})
    with OPENER.open(req, timeout=2) as response:
        return json.load(response)


def existing_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # Never trust an arbitrary URL from a local state file.
        port = state["port"]
        if type(port) is not int or not 1024 <= port <= 65535:
            return None
        url = f"http://127.0.0.1:{port}"
        if call_local(url + "/api/health").get("instance_id") == state.get("instance_id"):
            return {**state, "url": url}
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        pass
    return None


def stop_server():
    state = existing_state()
    if not state:
        print("没有找到本项目正在运行的服务；没有结束其他程序。", flush=True)
        return 0
    try:
        call_local(state["url"] + "/api/internal/shutdown", token=state["token"])
        for _ in range(30):
            time.sleep(0.1)
            if existing_state() is None:
                print("作品已关闭，纪念记录已保留。", flush=True)
                return 0
        print("已发送安全关闭请求；如仍在运行，请在启动窗口按 Ctrl+C。", flush=True)
        return 1
    except (OSError, KeyError, urllib.error.URLError) as exc:
        print(f"关闭失败（{type(exc).__name__}）；未强制结束任何进程。", flush=True)
        return 1


def bind_socket(first_port: int):
    for port in range(first_port, min(first_port + 11, 65536)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(128)
            sock.setblocking(False)
            return sock, port
        except OSError:
            sock.close()
    raise RuntimeError(f"端口 {first_port}—{min(first_port + 10, 65535)} 均不可用；请关闭不需要的程序后重试。本程序未结束其他进程。")


def start_background(port: int, no_browser: bool):
    """The Windows entry may exit without terminating the local HTTP service."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "server.log"
    kwargs = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log:
        child = subprocess.Popen(
            [sys.executable, str(ROOT / "run.py"), "--no-browser", "--port", str(port)],
            stdout=log, stderr=subprocess.STDOUT, **kwargs,
        )
    for _ in range(100):
        state = existing_state()
        if state:
            print(f"作品已在后台运行：{state['url']}\n启动窗口关闭后仍可使用；退出请运行 关闭作品.cmd。", flush=True)
            if not no_browser:
                webbrowser.open(state["url"])
            return 0
        if child.poll() is not None:
            print(f"本机服务启动失败，请查看日志：{log_path}", flush=True)
            return 1
        time.sleep(0.1)
    print(f"服务仍在启动，请稍后再次运行启动入口查看状态。日志：{log_path}", flush=True)
    return 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="节气讣告本地 Demo")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--background", action="store_true", help="后台启动，启动窗口退出后服务继续运行")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.stop:
        return stop_server()
    if not 1024 <= args.port <= 65525:
        parser.error("port 必须为 1024—65525")
    existing = existing_state()
    if existing:
        print(f"作品已经运行：{existing['url']}", flush=True)
        if not args.no_browser:
            webbrowser.open(existing["url"])
        return 0
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("缺少构建后的前端，请先运行 首次准备.cmd。", flush=True)
        return 1
    if args.background:
        return start_background(args.port, args.no_browser)
    try:
        import uvicorn
        from backend.app import create_app
    except ImportError:
        print("本地 Python 依赖尚未准备，请运行 首次准备.cmd。", flush=True)
        return 1
    try:
        sock, port = bind_socket(args.port)
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False))
        token = secrets.token_urlsafe(32)
        app.state.shutdown_token = token
        app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {"pid": os.getpid(), "port": port, "instance_id": app.state.instance_id, "token": token}
        STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        url = f"http://127.0.0.1:{port}"
        print(f"节气讣告——家乡旧候纪念馆\n浏览器地址：{url}\n关闭：在此窗口按 Ctrl+C，或运行 关闭作品.cmd。", flush=True)
        if port != args.port:
            print(f"默认端口被占用，已安全切换到 {port}。", flush=True)

        def open_ready():
            for _ in range(60):
                if server.started:
                    if not args.no_browser:
                        webbrowser.open(url)
                    return
                if server.should_exit:
                    return
                time.sleep(0.1)

        threading.Thread(target=open_ready, daemon=True).start()
        try:
            server.run(sockets=[sock])
        finally:
            sock.close()
            try:
                stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if stored.get("instance_id") == app.state.instance_id:
                    STATE_FILE.unlink()
            except (OSError, ValueError):
                pass
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"无法启动：{exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
