"""纯文本 / Markdown / 配置文件处理。"""

from __future__ import annotations

from typing import List

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import BaseHandler, Transformer
from .textio import read_text_with_encoding, write_text_with_encoding


class TextHandler(BaseHandler):
    name = "text"
    extensions = (
        ".txt",
        ".text",
        ".md",
        ".markdown",
        ".log",
        ".rst",
        ".ini",
        ".cfg",
        ".conf",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".htm",
        ".sql",
    )

    def extract_text(self, src: str) -> str:
        text, _ = read_text_with_encoding(src)
        return text

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        text, encoding = read_text_with_encoding(src)
        replacements: List[Replacement] = transform(text)
        output = apply_replacements(text, replacements)
        write_text_with_encoding(dst, output, encoding)
        warnings: List[str] = []
        if encoding in {"latin-1"}:
            warnings.append("未能确定原文件编码，已按 latin-1 读取，请检查输出内容")
        return warnings
