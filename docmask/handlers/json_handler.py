"""JSON / JSONL 处理。

仅处理字符串值，保持键名与结构不变。格式会被规范化（缩进/紧凑度按原文件风格）。
"""

from __future__ import annotations

import json
import os
from typing import Any, List

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import BaseHandler, Transformer
from .textio import read_text_with_encoding, write_text_with_encoding


class JsonHandler(BaseHandler):
    name = "json"
    extensions = (".json", ".jsonl", ".ndjson")

    def _walk(self, value: Any, transform: Transformer) -> Any:
        if isinstance(value, str):
            changes: List[Replacement] = transform(value)
            return apply_replacements(value, changes)
        if isinstance(value, list):
            return [self._walk(item, transform) for item in value]
        if isinstance(value, dict):
            return {key: self._walk(item, transform) for key, item in value.items()}
        return value

    def _collect(self, value: Any, out: List[str]) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for item in value:
                self._collect(item, out)
        elif isinstance(value, dict):
            for item in value.values():
                self._collect(item, out)

    def extract_text(self, src: str) -> str:
        text, _ = read_text_with_encoding(src)
        lines: List[str] = []
        is_jsonl = src.lower().endswith((".jsonl", ".ndjson"))
        try:
            if is_jsonl:
                for line in text.splitlines():
                    if line.strip():
                        self._collect(json.loads(line), lines)
            else:
                self._collect(json.loads(text), lines)
        except (json.JSONDecodeError, ValueError):
            return text
        return "\n".join(lines)

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        text, encoding = read_text_with_encoding(src)
        warnings: List[str] = []
        is_jsonl = src.lower().endswith((".jsonl", ".ndjson"))
        try:
            if is_jsonl:
                out_lines: List[str] = []
                for line in text.splitlines():
                    if not line.strip():
                        out_lines.append(line)
                        continue
                    obj = json.loads(line)
                    out_lines.append(
                        json.dumps(
                            self._walk(obj, transform),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                output = "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
            else:
                obj = json.loads(text)
                pretty = "\n" in text.strip()
                output = json.dumps(
                    self._walk(obj, transform),
                    ensure_ascii=False,
                    indent=2 if pretty else None,
                    separators=None if pretty else (",", ":"),
                )
                if text.endswith("\n"):
                    output += "\n"
        except json.JSONDecodeError as exc:
            # 结构损坏时按纯文本兜底，避免直接失败。
            changes: List[Replacement] = transform(text)
            output = apply_replacements(text, changes)
            warnings.append(f"JSON 解析失败，已按纯文本脱敏: {exc}")
        write_text_with_encoding(dst, output, encoding)
        return warnings
