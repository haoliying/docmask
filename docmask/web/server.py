"""本地 Web 服务：仅监听本机，无任何外部网络请求。"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import socket
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from .. import __version__
from ..config import build_policy
from ..entities import entity_list
from ..handlers import get_handler, load_builtin_handlers, supported_extensions
from ..models import Policy
from ..pipeline import InputFile, RedactionJob, preview_file, write_report

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 50
MAX_PREVIEW_BYTES = 60 * 1024 * 1024
MAX_BODY_BYTES = int(MAX_TOTAL_BYTES * 1.45)
JOB_TTL_SECONDS = 24 * 3600
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _data_root() -> Path:
    raw = os.environ.get("DOCMASK_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".docmask"
    )
    return Path(raw).expanduser().resolve()


def _policy_from_options(options: Dict[str, Any]) -> Policy:
    if not isinstance(options, dict):
        raise ValueError("options 必须是对象")
    rules: Dict[str, Any] = {}
    rules_text = options.get("rules_text")
    if rules_text:
        try:
            rules = json.loads(str(rules_text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"自定义规则 JSON 格式错误: {exc}") from exc
        if not isinstance(rules, dict):
            raise ValueError("自定义规则必须是 JSON 对象")
    enabled = options.get("enabled")
    if enabled is not None:
        if not isinstance(enabled, list):
            raise ValueError("enabled 必须是数组")
        enabled = [str(item).upper() for item in enabled]
    words = options.get("custom_words") or {}
    if not isinstance(words, dict):
        raise ValueError("custom_words 必须是对象")
    cleaned_words: Dict[str, List[str]] = {}
    total = 0
    for etype, items in words.items():
        if isinstance(items, str):
            items = items.splitlines()
        if not isinstance(items, list):
            continue
        values = []
        for item in items:
            word = str(item).strip()
            if 2 <= len(word) <= 100:
                values.append(word)
        total += len(values)
        if values:
            cleaned_words[str(etype).upper()] = values
    if total > 5000:
        raise ValueError("自定义词数量过多（最多 5000 个）")
    policy = build_policy(
        rules=rules,
        enabled=enabled,
        disabled=None,
        strategy=options.get("strategy"),
        mask_char=options.get("mask_char"),
        keep_length=bool(options.get("keep_length", False)),
        strip_metadata=bool(options.get("strip_metadata", True)),
        pdf_mode=options.get("pdf_mode"),
        custom_words=cleaned_words,
    )
    return policy


def _safe_filename(name: str) -> str:
    name = os.path.basename(str(name).replace("\\", "/"))
    name = name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        name = "upload"
    stem, ext = os.path.splitext(name)
    stem = stem[:120] or "upload"
    return stem + ext[:20]


def _decode_file(item: Dict[str, Any]) -> Tuple[str, bytes]:
    if not isinstance(item, dict):
        raise ValueError("文件项格式错误")
    name = _safe_filename(str(item.get("name", "")))
    raw = item.get("data")
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{name}: 缺少文件内容")
    if "," in raw[:200] and raw.lstrip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{name}: base64 内容无效") from exc
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{name}: 单个文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB")
    if not data:
        raise ValueError(f"{name}: 文件为空")
    if get_handler(name) is None:
        raise ValueError(f"{name}: 不支持的文件格式")
    return name, data


def _unique_name(name: str, used: set) -> str:
    stem, ext = os.path.splitext(name)
    candidate = name
    index = 1
    while candidate.lower() in used:
        candidate = f"{stem}_{index}{ext}"
        index += 1
    used.add(candidate.lower())
    return candidate


def _cleanup_jobs(root: Path) -> None:
    jobs_dir = root / "jobs"
    if not jobs_dir.is_dir():
        return
    now = time.time()
    for entry in jobs_dir.iterdir():
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > JOB_TTL_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


class App:
    def __init__(self, data_root: Optional[Path] = None, verbose: bool = True):
        self.root = (data_root or _data_root()).resolve()
        self.verbose = verbose
        self.jobs = self.root / "jobs"
        (self.jobs).mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._cleanup_lock = threading.Lock()
        self._last_cleanup = 0.0

    def maybe_cleanup(self) -> None:
        with self._cleanup_lock:
            now = time.time()
            if now - self._last_cleanup < 300:
                return
            self._last_cleanup = now
        _cleanup_jobs(self.root)


class Handler(BaseHTTPRequestHandler):
    server_version = f"docmask/{__version__}"
    protocol_version = "HTTP/1.1"
    app: App

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if getattr(self.server, "verbose", True):
            print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
        extra: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _check_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        if host in {"127.0.0.1", "localhost", "::1", "[::1]"}:
            return True
        if getattr(self.server, "allow_remote", False):
            return True
        self._error(HTTPStatus.FORBIDDEN, "仅允许通过本机地址访问")
        return False

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "Content-Length 无效")
            return None
        if length <= 0:
            self._error(HTTPStatus.BAD_REQUEST, "请求体为空")
            return None
        if length > MAX_BODY_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求体过大")
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "JSON 格式错误")
            return None
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "请求体必须是 JSON 对象")
            return None
        return payload

    def _decode_files(self, payload: Dict[str, Any]) -> Optional[List[Tuple[str, bytes]]]:
        items = payload.get("files")
        if not isinstance(items, list) or not items:
            self._error(HTTPStatus.BAD_REQUEST, "请选择至少一个文件")
            return None
        if len(items) > MAX_FILES:
            self._error(HTTPStatus.BAD_REQUEST, f"一次最多处理 {MAX_FILES} 个文件")
            return None
        used: set = set()
        files: List[Tuple[str, bytes]] = []
        total = 0
        for item in items:
            try:
                name, data = _decode_file(item)
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return None
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "文件总大小超限")
                return None
            files.append((_unique_name(name, used), data))
        return files

    # -------------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        if not self._check_host():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"}:
            self._serve_static("index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        if path == "/api/config":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "version": __version__,
                    "entities": entity_list(),
                    "strategies": [
                        {"key": "mask", "label": "全掩码", "hint": "统一替换为 ***"},
                        {
                            "key": "partial",
                            "label": "部分保留",
                            "hint": "保留首尾，如 138****8000",
                        },
                        {
                            "key": "replace",
                            "label": "占位符",
                            "hint": "替换为 [MOBILE_001]，可还原",
                        },
                        {"key": "hash", "label": "哈希", "hint": "稳定假名，不可还原"},
                    ],
                    "extensions": supported_extensions(),
                    "limits": {
                        "max_files": MAX_FILES,
                        "max_file_mb": MAX_FILE_BYTES // 1024 // 1024,
                        "max_total_mb": MAX_TOTAL_BYTES // 1024 // 1024,
                    },
                },
            )
            return
        if path.startswith("/download/"):
            job_id = path[len("/download/") :].strip("/")
            self._download(job_id)
            return
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True, "version": __version__})
            return
        self._error(HTTPStatus.NOT_FOUND, "未找到")

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_host():
            return
        path = urlparse(self.path).path
        if path not in {"/api/preview", "/api/redact"}:
            self._error(HTTPStatus.NOT_FOUND, "未找到")
            return
        payload = self._read_json()
        if payload is None:
            return
        origin = self.headers.get("Origin")
        if origin:
            expected = f"http://{self.headers.get('Host', '')}"
            if origin.rstrip("/") != expected:
                self._error(HTTPStatus.FORBIDDEN, "来源校验失败")
                return
        try:
            options = payload.get("options") or {}
            policy = _policy_from_options(options)
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        files = self._decode_files(payload)
        if files is None:
            return
        try:
            if path == "/api/preview":
                self._preview(files, policy)
            else:
                self._redact(files, policy)
        except Exception as exc:  # pragma: no cover - 防御性
            traceback.print_exc()
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"处理失败: {exc}")

    # -------------------------------------------------------------------- views
    def _serve_static(self, relative: str) -> None:
        if ".." in relative or relative.startswith("/"):
            self._error(HTTPStatus.NOT_FOUND, "未找到")
            return
        target = (_STATIC_DIR / relative).resolve()
        if _STATIC_DIR.resolve() not in target.parents and target != _STATIC_DIR.resolve():
            self._error(HTTPStatus.NOT_FOUND, "未找到")
            return
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "未找到")
            return
        data = target.read_bytes()
        ctype = _MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(HTTPStatus.OK, data, ctype)

    def _preview(self, files: List[Tuple[str, bytes]], policy: Policy) -> None:
        root = Path(self.server.app.root) / "preview" / uuid.uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        results = []
        total_bytes = 0
        try:
            for name, data in files:
                total_bytes += len(data)
                if total_bytes > MAX_PREVIEW_BYTES:
                    results.append(
                        {
                            "source": name,
                            "total": 0,
                            "counts": {},
                            "items": [],
                            "error": "文件总量超过预览上限，可直接执行脱敏",
                        }
                    )
                    continue
                temp_path = root / name
                temp_path.write_bytes(data)
                try:
                    preview = preview_file(str(temp_path), policy, max_items=8)
                    results.append(
                        {
                            "source": name,
                            "total": preview.total,
                            "counts": preview.counts,
                            "items": [
                                {
                                    "type": item.type,
                                    "label": item.label,
                                    "preview": item.preview,
                                    "confidence": item.confidence,
                                }
                                for item in preview.items
                            ],
                            "error": preview.error,
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "source": name,
                            "total": 0,
                            "counts": {},
                            "items": [],
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                finally:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self._json(
            HTTPStatus.OK,
            {
                "ok": True,
                "files": results,
                "total": sum(item.get("total", 0) for item in results),
            },
        )

    def _redact(self, files: List[Tuple[str, bytes]], policy: Policy) -> None:
        app = self.server.app
        app.maybe_cleanup()
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        job_dir = app.jobs / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(job_dir, 0o700)
        except OSError:
            pass
        inputs: List[InputFile] = []
        try:
            for name, data in files:
                target = input_dir / name
                target.write_bytes(data)
                inputs.append(InputFile(str(target), name))
            report_path = output_dir / "redaction_report.json"
            job = RedactionJob(
                policy,
                str(output_dir),
                mapping_path=None,
                report_path=str(report_path),
                dry_run=False,
            )
            summary = job.run(inputs)
            # 输入原件立即删除，不在磁盘上保留敏感源文件
            shutil.rmtree(input_dir, ignore_errors=True)
            mapping_included = bool(
                job.mapping_path and os.path.exists(job.mapping_path)
            )

            zip_path = job_dir / "result.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(output_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, path.relative_to(output_dir).as_posix())
                note = _result_note(policy, summary)
                zf.writestr("脱敏说明.txt", note)
            shutil.rmtree(output_dir, ignore_errors=True)

            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "job_id": job_id,
                    "download": f"/download/{job_id}",
                    "summary": {
                        "files": len(summary.files),
                        "ok": summary.ok_files,
                        "failed": summary.failed_files,
                        "total": summary.total_entities,
                        "counts": summary.counts,
                    },
                    "files": [
                        {
                            "source": item.source,
                            "status": item.status,
                            "counts": item.counts,
                            "warnings": item.warnings,
                            "error": item.error,
                        }
                        for item in summary.files
                    ],
                    "mapping_included": mapping_included,
                },
            )
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    def _download(self, job_id: str) -> None:
        if not _JOB_ID_RE.match(job_id):
            self._error(HTTPStatus.NOT_FOUND, "任务不存在或已过期")
            return
        job_dir = (Path(self.server.app.root) / "jobs" / job_id).resolve()
        jobs_root = (Path(self.server.app.root) / "jobs").resolve()
        if job_dir.parent != jobs_root:
            self._error(HTTPStatus.NOT_FOUND, "任务不存在或已过期")
            return
        zip_path = job_dir / "result.zip"
        if not zip_path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "任务不存在或已过期")
            return
        size = zip_path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", 'attachment; filename="docmask_result.zip"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with open(zip_path, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile, length=256 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _result_note(policy: Policy, summary) -> str:
    lines = [
        "docmask 本地脱敏结果",
        "=" * 32,
        f"策略: {policy.strategy}",
        f"文件: {len(summary.files)} 个，成功 {summary.ok_files}，失败 {summary.failed_files}",
        f"命中: {summary.total_entities} 处",
        "",
        "实体统计:",
    ]
    for etype, count in summary.counts.items():
        lines.append(f"  {etype}: {count}")
    lines.append("")
    if policy.strategy == "replace":
        lines.append("mapping.csv 含敏感原文与占位符对应关系，请与脱敏文件分开保管。")
    lines.append("提示：图片、扫描件、批注、图表等非文本内容不会被自动脱敏，请人工复核。")
    for item in summary.files:
        for warning in item.warnings:
            lines.append(f"[{item.source}] {warning}")
    return "\n".join(lines) + "\n"


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    load_builtin_handlers()
    root = _data_root()
    app = App(root)
    Handler.app = app
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    httpd = None
    actual_port = port
    for offset in range(0, 20):
        try:
            actual_port = port + offset
            httpd = Server((host, actual_port), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        raise RuntimeError(f"无法监听 {host}:{port}，端口可能被占用")
    httpd.verbose = True  # type: ignore[attr-defined]
    httpd.allow_remote = not loopback  # type: ignore[attr-defined]
    httpd.app = app  # type: ignore[attr-defined]
    shown_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    url = f"http://{shown_host}:{actual_port}/"
    print(f"docmask {__version__} 本地服务已启动")
    print(f"  访问地址  {url}")
    print(f"  数据目录  {root}")
    print("  所有处理均在本机完成，不会发起外部网络请求")
    print("  Ctrl+C 停止")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.3)
    finally:
        httpd.server_close()
