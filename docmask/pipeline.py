"""批处理管线：收集文件、执行脱敏、生成报告、还原。"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__
from .entities import DEFAULT_ENABLED, label_of
from .handlers import get_handler, load_builtin_handlers, supported_extensions
from .masking import Masker, Redactor, Restorer, apply_replacements, load_mapping
from .models import (
    FileOutcome,
    FilePreview,
    JobSummary,
    Policy,
    PreviewItem,
    Replacement,
)

_IGNORED_NAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}


@dataclass
class InputFile:
    source: str
    relative: str


def _is_ignored(path: str) -> bool:
    name = os.path.basename(path)
    if name in _IGNORED_NAMES or name.startswith("~$") or name.startswith(".~"):
        return True
    return False


def _supported(path: str) -> bool:
    return get_handler(path) is not None


def collect_inputs(
    paths: Sequence[str],
    recursive: bool = True,
    exclude_dirs: Sequence[str] = (),
) -> Tuple[List[InputFile], int]:
    """展开输入路径，返回 (文件列表, 因格式不支持而跳过的数量)。"""
    load_builtin_handlers()
    files: List[InputFile] = []
    skipped = 0
    excluded = [os.path.abspath(p) for p in exclude_dirs if p]

    def is_excluded(path: str) -> bool:
        absolute = os.path.abspath(path)
        for root in excluded:
            if absolute == root or absolute.startswith(root + os.sep):
                return True
        return False

    for raw in paths:
        source = os.path.abspath(os.path.expanduser(raw))
        if os.path.isfile(source):
            if _is_ignored(source):
                continue
            if _supported(source):
                files.append(InputFile(source, os.path.basename(source)))
            else:
                skipped += 1
            continue
        if os.path.isdir(source):
            if recursive:
                walker = os.walk(source, followlinks=False)
            else:
                try:
                    names = sorted(os.listdir(source))
                except OSError:
                    continue
                walker = [(source, [], [n for n in names if os.path.isfile(os.path.join(source, n))])]
            for root, dirs, names in walker:
                if is_excluded(root):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if not is_excluded(os.path.join(root, d)) and not d.startswith(".")
                )
                for name in sorted(names):
                    path = os.path.join(root, name)
                    if _is_ignored(path):
                        continue
                    if not _supported(path):
                        skipped += 1
                        continue
                    rel = os.path.relpath(path, source)
                    files.append(InputFile(path, rel))
            continue
        raise FileNotFoundError(f"输入路径不存在: {raw}")
    return files, skipped


def _safe_rel(rel: str) -> str:
    parts = []
    for part in rel.replace("\\", "/").split("/"):
        if part in ("", ".", ".."):
            continue
        parts.append(part)
    return os.path.join(*parts) if parts else "file"


def _unique_path(path: str, used: set) -> str:
    base, ext = os.path.splitext(path)
    candidate = path
    index = 1
    while os.path.abspath(candidate) in used:
        candidate = f"{base}_{index}{ext}"
        index += 1
    used.add(os.path.abspath(candidate))
    return candidate


def _counts_delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for key, value in after.items():
        diff = value - before.get(key, 0)
        if diff:
            result[key] = diff
    return result


class RedactionJob:
    def __init__(
        self,
        policy: Policy,
        out_dir: str,
        mapping_path: Optional[str] = None,
        report_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        policy.validate()
        load_builtin_handlers()
        self.policy = policy
        self.out_dir = os.path.abspath(out_dir)
        self.report_path = report_path
        self.dry_run = dry_run
        self.masker = Masker(policy)
        self.redactor = Redactor(policy, self.masker)
        if mapping_path:
            self.mapping_path: Optional[str] = os.path.abspath(mapping_path)
        elif policy.strategy == "replace" and not dry_run:
            self.mapping_path = os.path.join(self.out_dir, "mapping.csv")
        else:
            self.mapping_path = None
        self._used_outputs: set = set()
        self._temp_dir: Optional[str] = None
        if dry_run:
            self._temp_dir = tempfile.mkdtemp(prefix="docmask_dry_")

    def close(self) -> None:
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None

    def _destination(self, src: str, rel: str) -> str:
        target_root = self._temp_dir if self.dry_run else self.out_dir
        assert target_root is not None
        rel = _safe_rel(rel)
        dst = os.path.join(target_root, rel)
        if os.path.abspath(dst) == os.path.abspath(src):
            base, ext = os.path.splitext(dst)
            dst = f"{base}_redacted{ext}"
        return _unique_path(dst, self._used_outputs)

    def process_one(self, item: InputFile) -> FileOutcome:
        started = time.perf_counter()
        handler = get_handler(item.source)
        if handler is None:
            return FileOutcome(
                source=item.relative,
                status="skipped",
                error="不支持的文件格式",
            )
        dst = self._destination(item.source, item.relative)
        adjusted = handler.adjust_destination(item.source, dst)
        if adjusted != dst:
            dst = _unique_path(adjusted, self._used_outputs)
        before = dict(self.masker.counts)
        try:
            warnings = handler.process(
                item.source, dst, self.redactor.transform, self.policy
            )
            counts = _counts_delta(before, self.masker.counts)
            return FileOutcome(
                source=item.relative,
                output=None if self.dry_run else os.path.relpath(dst, self.out_dir),
                status="ok",
                counts=counts,
                warnings=warnings,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # 单个文件失败不影响整批
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            return FileOutcome(
                source=item.relative,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

    def run(self, files: Sequence[InputFile]) -> JobSummary:
        summary = JobSummary()
        try:
            if not self.dry_run:
                os.makedirs(self.out_dir, exist_ok=True)
            for item in files:
                summary.files.append(self.process_one(item))
            self._finalize(summary)
        finally:
            self.close()
        return summary

    def _finalize(self, summary: JobSummary) -> None:
        if self.dry_run:
            return
        if self.mapping_path and self.masker.entries:
            self.masker.write_mapping(self.mapping_path)
        if self.report_path:
            write_report(self.report_path, summary, self.policy, self.mapping_path)


def write_report(
    path: str,
    summary: JobSummary,
    policy: Policy,
    mapping_path: Optional[str] = None,
) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {
        "tool": "docmask",
        "version": __version__,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "policy": {
            "strategy": policy.strategy,
            "mask_char": policy.mask_char,
            "keep_length": policy.keep_length,
            "strip_metadata": policy.strip_metadata,
            "pdf_mode": policy.pdf_mode,
            "enabled": sorted(policy.enabled),
            "custom_word_count": sum(len(v) for v in policy.custom_words.values()),
        },
        "mapping_written": bool(mapping_path and os.path.exists(mapping_path)),
        "summary": {
            "files": len(summary.files),
            "ok": summary.ok_files,
            "failed": summary.failed_files,
            "entities": summary.counts,
            "total_entities": summary.total_entities,
        },
        "files": [
            {
                "source": item.source,
                "output": item.output,
                "status": item.status,
                "counts": item.counts,
                "total": item.total,
                "warnings": item.warnings,
                "error": item.error,
                "elapsed_ms": item.elapsed_ms,
            }
            for item in summary.files
        ],
    }
    if path.lower().endswith(".csv"):
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["source", "status", "total", "entities", "output", "error"])
            for item in summary.files:
                entities = ";".join(f"{k}={v}" for k, v in item.counts.items())
                writer.writerow(
                    [
                        item.source,
                        item.status,
                        item.total,
                        entities,
                        item.output or "",
                        item.error or "",
                    ]
                )
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------- preview
def preview_file(path: str, policy: Policy, max_items: int = 8) -> FilePreview:
    load_builtin_handlers()
    handler = get_handler(path)
    name = os.path.basename(path)
    if handler is None:
        return FilePreview(source=name, counts={}, error="不支持的文件格式")
    try:
        text = handler.extract_text(path)
    except Exception as exc:
        return FilePreview(
            source=name, counts={}, error=f"{type(exc).__name__}: {exc}"
        )
    redactor = Redactor(policy)
    matches = redactor.engine.detect(text)
    counts: Dict[str, int] = {}
    for match in matches:
        counts[match.etype] = counts.get(match.etype, 0) + 1
    items: List[PreviewItem] = []
    for match in matches[:max_items]:
        window_start = max(0, match.start - 10)
        window_end = min(len(text), match.end + 16)
        # 避免从敏感信息中间截断
        changed = True
        while changed:
            changed = False
            for other in matches:
                if other.start < window_start < other.end:
                    window_start = other.start
                    changed = True
                if other.start < window_end < other.end:
                    window_end = other.end
                    changed = True
        snippet = text[window_start:window_end]
        snippet_matches = [
            m for m in matches if m.end > window_start and m.start < window_end
        ]
        replacements = [
            Replacement(
                start=max(0, m.start - window_start),
                end=min(window_end, m.end) - window_start,
                text=redactor.masker.render(m),
            )
            for m in snippet_matches
        ]
        masked = apply_replacements(snippet, replacements)
        masked = " ".join(masked.split())
        prefix = "…" if window_start > 0 else ""
        suffix = "…" if window_end < len(text) else ""
        items.append(
            PreviewItem(
                type=match.etype,
                label=label_of(match.etype),
                preview=f"{prefix}{masked}{suffix}",
                confidence=match.confidence,
            )
        )
    return FilePreview(source=name, counts=counts, items=items)


# ---------------------------------------------------------------------- restore
class RestoreJob:
    def __init__(
        self,
        mapping_path: str,
        out_dir: str,
        policy: Optional[Policy] = None,
        report_path: Optional[str] = None,
    ):
        load_builtin_handlers()
        self.mapping_path = os.path.abspath(mapping_path)
        self.restorer = Restorer(load_mapping(mapping_path))
        self.out_dir = os.path.abspath(out_dir)
        self.policy = policy or Policy(
            enabled=set(DEFAULT_ENABLED), strip_metadata=False
        )
        self.report_path = report_path
        self._used_outputs: set = set()

    def run(self, files: Sequence[InputFile]) -> JobSummary:
        summary = JobSummary()
        os.makedirs(self.out_dir, exist_ok=True)
        skip = {self.mapping_path}
        if self.report_path:
            skip.add(os.path.abspath(self.report_path))
        for item in files:
            if os.path.abspath(item.source) in skip:
                continue
            if os.path.basename(item.source) == "redaction_report.json":
                continue
            started = time.perf_counter()
            handler = get_handler(item.source)
            if handler is None or not handler.can_restore():
                summary.files.append(
                    FileOutcome(
                        source=item.relative,
                        status="skipped",
                        error="该格式不支持还原",
                    )
                )
                continue
            rel = _safe_rel(item.relative)
            dst = _unique_path(os.path.join(self.out_dir, rel), self._used_outputs)
            adjusted = handler.adjust_destination(item.source, dst)
            if adjusted != dst:
                dst = _unique_path(adjusted, self._used_outputs)
            before = self.restorer.count
            try:
                warnings = handler.process(
                    item.source, dst, self.restorer.transform, self.policy
                )
                restored = self.restorer.count - before
                summary.files.append(
                    FileOutcome(
                        source=item.relative,
                        output=os.path.relpath(dst, self.out_dir),
                        status="ok",
                        counts={"RESTORE": restored} if restored else {},
                        warnings=warnings,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
            except Exception as exc:
                if os.path.exists(dst):
                    try:
                        os.remove(dst)
                    except OSError:
                        pass
                summary.files.append(
                    FileOutcome(
                        source=item.relative,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
        if self.report_path:
            write_report(self.report_path, summary, self.policy)
        return summary


def supported_formats_text() -> str:
    return "  ".join(supported_extensions())
