"""桌面窗口模式：把本地界面放进原生窗口，使用体验接近普通 EXE 程序。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Iterator, Optional

from . import __version__
from .web.server import start_server

WINDOW_TITLE = "docmask · 本地文档脱敏"
SMOKE_ENV = "DOCMASK_SMOKE_REPORT"
_LOG_PATH = Path(tempfile.gettempdir()) / "docmask-desktop.log"


def _log(message: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _message_box(text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "docmask", 0x10)
    except Exception:
        pass


def _resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _icon_path() -> Optional[str]:
    candidate = _resource_dir() / "assets" / "docmask.ico"
    return str(candidate) if candidate.is_file() else None


def _browser_candidates() -> Iterator[str]:
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    relatives = (
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Google/Chrome/Application/chrome.exe"),
    )
    for root in roots:
        if not root:
            continue
        for relative in relatives:
            candidate = Path(root) / relative
            if candidate.is_file():
                yield str(candidate)
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            yield found


def _open_app_window(url: str) -> bool:
    """没有 WebView2 时用 Edge/Chrome 的无地址栏 --app 窗口兜底。"""
    for exe in _browser_candidates():
        try:
            proc = subprocess.Popen([exe, f"--app={url}", "--window-size=1280,880"])
        except OSError:
            continue
        _log(f"使用 --app 窗口: {exe}")
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        return True
    return False


def _write_report(path: str, loaded: bool, url: str, error: str = "") -> None:
    payload = {"loaded": loaded, "url": url, "version": __version__, "error": error}
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        _log(f"写入冒烟报告失败: {exc}")


def _run_native(url: str, smoke_report: Optional[str]) -> int:
    import webview  # 延迟导入，缺少桌面组件时不影响其他模式

    # pywebview 默认取消下载，显式开启后由它弹出系统“另存为”对话框。
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        _log("当前 pywebview 版本不支持 ALLOW_DOWNLOADS")

    window = webview.create_window(
        WINDOW_TITLE,
        url,
        width=1280,
        height=880,
        min_size=(980, 640),
        background_color="#F4EFE8",
    )
    loaded = {"ok": False}

    def _mark_loaded() -> None:
        loaded["ok"] = True

    window.events.loaded += _mark_loaded

    if smoke_report:
        def _closer() -> None:
            deadline = time.time() + 40
            while time.time() < deadline and not loaded["ok"]:
                time.sleep(0.2)
            time.sleep(1.0)
            try:
                window.destroy()
            except Exception:
                pass

        threading.Thread(target=_closer, daemon=True).start()

    _log(f"启动原生窗口 {url}")
    webview.start(icon=_icon_path(), gui="edgechromium", private_mode=True)
    if smoke_report:
        _write_report(smoke_report, loaded["ok"], url)
        return 0 if loaded["ok"] else 3
    return 0


def run_app(host: str = "127.0.0.1", port: int = 8765) -> int:
    """启动本地服务并打开原生窗口；异常时逐级降级到 --app 窗口和浏览器。"""
    httpd, url, _root = start_server(host, port, announce=True)
    worker = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True
    )
    worker.start()
    smoke_report = os.environ.get(SMOKE_ENV)
    try:
        if smoke_report:
            try:
                return _run_native(url, smoke_report)
            except Exception as exc:
                _log("桌面窗口冒烟失败:\n" + traceback.format_exc())
                _write_report(smoke_report, False, url, str(exc))
                return 4
        try:
            return _run_native(url, None)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            _log("原生窗口启动失败:\n" + traceback.format_exc())
            if _open_app_window(url):
                return 0
            _message_box(f"无法打开桌面窗口，将改用浏览器。\n\n{exc}")
            webbrowser.open(url)
            threading.Event().wait()
            return 0
    finally:
        httpd.shutdown()
        httpd.server_close()
