"""PDF 处理（基于 PyMuPDF）。

对可提取文本的 PDF 做真正的文本移除（redaction），而不是简单盖上一层色块：
redaction 后再以 garbage=4 保存，原始文本不会残留在内容流中。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..models import Policy, Replacement
from .base import BaseHandler, Transformer

try:
    import pymupdf  # type: ignore
except Exception:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except Exception:
        pymupdf = None  # type: ignore


class PdfHandler(BaseHandler):
    name = "pdf"
    extensions = (".pdf",)

    def _open(self, src: str):
        if pymupdf is None:
            raise RuntimeError("缺少 PyMuPDF 依赖，无法处理 .pdf（请离线安装依赖）")
        doc = pymupdf.open(src)
        if doc.needs_pass:
            if not doc.authenticate(""):
                doc.close()
                raise ValueError("PDF 已加密，无法处理")
        return doc

    def extract_text(self, src: str) -> str:
        doc = self._open(src)
        try:
            return "\n".join(page.get_text("text") for page in doc)
        finally:
            doc.close()

    @staticmethod
    def _font_for(text: str) -> str:
        return "china-s" if any(ord(ch) > 127 for ch in text) else "helv"

    def _fontsize(self, text: str, rect, fontname: str) -> float:
        size = max(4.0, min(11.0, rect.height * 0.72))
        while size > 4.0:
            try:
                width = pymupdf.get_text_length(text, fontname=fontname, fontsize=size)
            except Exception:
                break
            if width <= rect.width:
                break
            size -= 0.5
        return size

    def _insert_text(self, page, rect, text: str) -> bool:
        fontname = self._font_for(text)
        size = self._fontsize(text, rect, fontname)
        try:
            result = page.insert_textbox(
                rect,
                text,
                fontsize=size,
                fontname=fontname,
                color=(0, 0, 0),
                align=0,
            )
            if result >= 0:
                return True
            page.insert_text(
                (rect.x0, rect.y1 - 1),
                text,
                fontsize=max(2.0, size),
                fontname=fontname,
                color=(0, 0, 0),
            )
            return True
        except Exception:
            return False

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        doc = self._open(src)
        warnings: List[str] = []
        blank_pages = 0
        missing: Dict[str, int] = {}
        insert_failed = 0
        try:
            for page in doc:
                text = page.get_text("text")
                if not text.strip():
                    blank_pages += 1
                    continue
                changes: List[Replacement] = transform(text)
                if not changes:
                    continue
                seen_rects = set()
                insertions: List[Tuple[object, str]] = []
                for change in changes:
                    value = text[change.start : change.end]
                    if not value:
                        continue
                    rects = page.search_for(value)
                    if not rects:
                        missing[value[:4] + "…"] = missing.get(value[:4] + "…", 0) + 1
                        continue
                    first = True
                    for rect in rects:
                        key = (
                            round(rect.x0, 1),
                            round(rect.y0, 1),
                            round(rect.x1, 1),
                            round(rect.y1, 1),
                        )
                        if key in seen_rects:
                            continue
                        seen_rects.add(key)
                        page.add_redact_annot(
                            rect,
                            fill=(0.1, 0.1, 0.1) if policy.pdf_mode == "box" else (1, 1, 1),
                            cross_out=False,
                        )
                        if policy.pdf_mode == "text" and first:
                            insertions.append((rect, change.text))
                        first = False
                page.apply_redactions()
                for rect, replacement in insertions:
                    if not self._insert_text(page, rect, replacement):
                        insert_failed += 1

            if blank_pages:
                warnings.append(
                    f"{blank_pages} 页未提取到文本，可能为扫描件；扫描件请先 OCR 后再脱敏"
                )
            if missing:
                total = sum(missing.values())
                warnings.append(
                    f"有 {total} 处命中无法在页面上精确定位（可能跨行或被特殊编码），"
                    "建议人工复核"
                )
            if insert_failed:
                warnings.append(
                    f"有 {insert_failed} 处掩码文本因页面空间不足未能写入，该处内容已被移除"
                )
            if policy.strip_metadata:
                try:
                    doc.set_metadata({})
                except Exception:
                    pass
                try:
                    doc.del_xml_metadata()
                except Exception:
                    pass
                try:
                    for name in list(doc.embfile_names()):
                        doc.embfile_del(name)
                        warnings.append("已移除 PDF 内嵌附件")
                except Exception:
                    pass
            self._ensure_parent(dst)
            doc.save(dst, garbage=4, deflate=True, clean=True)
        finally:
            doc.close()
        return warnings

    def can_restore(self) -> bool:
        return False
