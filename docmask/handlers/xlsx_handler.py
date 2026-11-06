"""Excel (.xlsx) 处理。"""

from __future__ import annotations

import io
import os
from typing import List

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import BaseHandler, Transformer

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover
    load_workbook = None  # type: ignore


class XlsxHandler(BaseHandler):
    name = "xlsx"
    extensions = (".xlsx",)

    def _load(self, src: str):
        if load_workbook is None:
            raise RuntimeError("缺少 openpyxl 依赖，无法处理 .xlsx（请离线安装依赖）")
        # openpyxl 会按扩展名拒绝打开，这里对“扩展名与实际格式不一致”的文件改用字节流读取。
        if os.path.splitext(src)[1].lower() not in (".xlsx", ".xlsm", ".xltx", ".xltm"):
            with open(src, "rb") as fh:
                return load_workbook(io.BytesIO(fh.read()))
        return load_workbook(src)

    def _header_footer_texts(self, ws) -> List[object]:
        parts: List[object] = []
        for name in (
            "oddHeader",
            "oddFooter",
            "evenHeader",
            "evenFooter",
            "firstHeader",
            "firstFooter",
        ):
            item = getattr(ws, name, None)
            if item is None:
                continue
            for side in ("left", "center", "centre", "right"):
                part = getattr(item, side, None)
                if part is not None and getattr(part, "text", None):
                    parts.append(part)
        return parts

    def extract_text(self, src: str) -> str:
        wb = self._load(src)
        lines: List[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        lines.append(cell.value)
                    if cell.comment is not None and cell.comment.text:
                        lines.append(cell.comment.text)
            for part in self._header_footer_texts(ws):
                lines.append(part.text)
        wb.close()
        return "\n".join(lines)

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        wb = self._load(src)
        warnings: List[str] = []
        formula_found = False
        image_found = False
        for ws in wb.worksheets:
            if getattr(ws, "_images", None):
                image_found = True
            for row in ws.iter_rows():
                for cell in row:
                    value = cell.value
                    if isinstance(value, str):
                        if value.startswith("="):
                            formula_found = True
                        else:
                            changes: List[Replacement] = transform(value)
                            if changes:
                                cell.value = apply_replacements(value, changes)
                    if cell.comment is not None:
                        comment = cell.comment
                        if comment.text:
                            changes = transform(comment.text)
                            if changes:
                                comment.text = apply_replacements(comment.text, changes)
                        if policy.strip_metadata:
                            try:
                                comment.author = "匿名"
                            except Exception:
                                pass
                    hyperlink = getattr(cell, "hyperlink", None)
                    if hyperlink is not None and hyperlink.target:
                        changes = transform(hyperlink.target)
                        if changes:
                            hyperlink.target = apply_replacements(hyperlink.target, changes)
            for part in self._header_footer_texts(ws):
                old = part.text
                changes = transform(old)
                if changes:
                    part.text = apply_replacements(old, changes)

        if formula_found:
            warnings.append("表格含公式，公式文本本身未脱敏；公式缓存值在保存后会由 Excel 重新计算")
        if image_found:
            warnings.append("表格内含图片，图片中的文字不会被 OCR 识别，请人工检查")
        if policy.strip_metadata:
            props = wb.properties
            for attr in (
                "creator",
                "lastModifiedBy",
                "title",
                "subject",
                "description",
                "keywords",
                "category",
            ):
                try:
                    setattr(props, attr, "")
                except Exception:
                    pass
        try:
            wb.calculation.fullCalcOnLoad = True
        except Exception:
            pass
        self._ensure_parent(dst)
        wb.save(dst)
        wb.close()
        return warnings
