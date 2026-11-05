"""脱敏渲染、占位符映射与还原。"""

from __future__ import annotations

import csv
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from typing import Dict, List, Optional, Pattern, Tuple

from .detectors import DetectionEngine
from .entities import PARTIAL_KEEP, TOKEN_PREFIX
from .models import Match, Policy, Replacement


@dataclass
class MappingEntry:
    etype: str
    original: str
    replacement: str
    count: int = 0


class Masker:
    """把命中转换为具体替换文本，并维护跨文件的映射一致性。"""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.salt = policy.salt or secrets.token_hex(16)
        self.counts: Dict[str, int] = {}
        self.entries: Dict[Tuple[str, str], MappingEntry] = {}
        self._counters: Dict[str, int] = {}

    # ------------------------------------------------------------------ render
    def render(self, match: Match) -> str:
        key = (match.etype, match.value)
        entry = self.entries.get(key)
        if entry is None:
            entry = MappingEntry(
                etype=match.etype,
                original=match.value,
                replacement=self._make_replacement(match),
            )
            self.entries[key] = entry
        entry.count += 1
        self.counts[match.etype] = self.counts.get(match.etype, 0) + 1
        return entry.replacement

    def _make_replacement(self, match: Match) -> str:
        strategy = self.policy.strategy
        if strategy == "mask":
            length = len(match.value) if self.policy.keep_length else 3
            return self.policy.mask_char * max(1, min(length, 64))
        if strategy == "partial":
            return self._partial(match.etype, match.value)
        if strategy == "replace":
            return self._token(match.etype)
        if strategy == "hash":
            digest = hmac.new(
                self.salt.encode("utf-8"),
                f"{match.etype}:{match.value}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()[:10]
            return f"[H_{digest}]"
        raise ValueError(f"未知脱敏策略: {strategy}")

    def _partial(self, etype: str, value: str) -> str:
        if etype == "EMAIL" and "@" in value:
            local, domain = value.split("@", 1)
            head = local[:1] if local else self.policy.mask_char
            return f"{head}{self.policy.mask_char * 3}@{domain}"
        pre, post = PARTIAL_KEEP.get(etype, (2, 2))
        length = len(value)
        if length <= pre + post:
            return self.policy.mask_char * max(1, length)
        middle = length - pre - post
        masked = self.policy.mask_char * middle
        if post:
            return f"{value[:pre]}{masked}{value[-post:]}"
        return f"{value[:pre]}{masked}"

    def _token(self, etype: str) -> str:
        prefix = TOKEN_PREFIX.get(etype, re.sub(r"[^A-Z0-9_]", "", etype.upper())[:12] or "MASK")
        number = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = number
        return f"[{prefix}_{number:03d}]"

    # ----------------------------------------------------------------- mapping
    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def write_mapping(self, path: str) -> None:
        """写出原始值到替换值的映射。

        文件包含敏感原文，权限会被设置为仅当前用户可读写（POSIX）。
        """
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["type", "original", "replacement", "count"])
            for entry in self.entries.values():
                writer.writerow([entry.etype, entry.original, entry.replacement, entry.count])
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


class Redactor:
    """检测 + 渲染，供各格式处理器调用。"""

    def __init__(self, policy: Policy, masker: Optional[Masker] = None):
        self.policy = policy
        self.engine = DetectionEngine(policy)
        self.masker = masker or Masker(policy)

    def transform(self, text: str) -> List[Replacement]:
        matches = self.engine.detect(text)
        return self.replacements(text, matches)

    def replacements(self, text: str, matches: List[Match]) -> List[Replacement]:
        result: List[Replacement] = []
        for match in matches:
            result.append(
                Replacement(
                    start=match.start,
                    end=match.end,
                    text=self.masker.render(match),
                    etype=match.etype,
                )
            )
        return result


def apply_replacements(text: str, replacements: List[Replacement]) -> str:
    if not replacements:
        return text
    parts: List[str] = []
    cursor = 0
    for item in sorted(replacements, key=lambda r: (r.start, r.end)):
        if item.start < cursor:
            continue
        parts.append(text[cursor : item.start])
        parts.append(item.text)
        cursor = item.end
    parts.append(text[cursor:])
    return "".join(parts)


def load_mapping(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"映射文件不存在: {path}")
    mapping: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"original", "replacement"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("映射文件缺少 original / replacement 列")
        for row in reader:
            replacement = (row.get("replacement") or "").strip()
            original = row.get("original") or ""
            if replacement and replacement not in mapping:
                mapping[replacement] = original
    if not mapping:
        raise ValueError("映射文件为空")
    return mapping


class Restorer:
    """根据映射文件把占位符还原为原文。"""

    def __init__(self, mapping: Dict[str, str]):
        self.mapping = mapping
        ordered = sorted(mapping, key=len, reverse=True)
        self.pattern: Pattern[str] = re.compile("|".join(re.escape(k) for k in ordered))
        self.count = 0

    def transform(self, text: str) -> List[Replacement]:
        if not text:
            return []
        result: List[Replacement] = []
        for match in self.pattern.finditer(text):
            token = match.group(0)
            if token not in self.mapping:
                continue
            self.count += 1
            result.append(
                Replacement(
                    start=match.start(),
                    end=match.end(),
                    text=self.mapping[token],
                    etype="RESTORE",
                )
            )
        return result
