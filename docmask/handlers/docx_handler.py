"""Word (.docx) 处理。

在 XML 段落级合并 run 文本后检测，再把替换结果回写到各 run，
以解决“敏感信息被 Word 拆成多个 run”导致的漏检，同时尽量保留格式。
"""

from __future__ import annotations

import os
import zipfile
from typing import Iterable, List, Optional, Tuple

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import BaseHandler, Transformer
from .runutils import redistribute_runs

try:  # 延迟到运行时给出更友好的错误
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.run import Run
except Exception:  # pragma: no cover
    Document = None  # type: ignore
    qn = None  # type: ignore
    Run = None  # type: ignore

_WORD_PARTS = (
    "/word/document.xml",
    "/word/header",
    "/word/footer",
    "/word/comments",
    "/word/footnotes",
    "/word/endnotes",
)


def _iter_runs(paragraph):
    """只返回属于当前段落（不包含嵌套文本框段落）的 run。"""
    for run in paragraph.iter(qn("w:r")):
        node = run.getparent()
        while node is not None and node.tag != qn("w:p"):
            node = node.getparent()
        if node is paragraph:
            yield run


def _run_text(run) -> str:
    return Run(run, None).text or ""


def _paragraph_text(paragraph) -> str:
    return "".join(_run_text(r) for r in _iter_runs(paragraph))


def _transform_paragraph(paragraph, transform: Transformer) -> bool:
    runs = list(_iter_runs(paragraph))
    if not runs:
        return False
    texts = [_run_text(r) for r in runs]
    full = "".join(texts)
    if not full:
        return False
    changes: List[Replacement] = transform(full)
    if not changes:
        return False
    new_texts = redistribute_runs(texts, changes)
    for run, old, new in zip(runs, texts, new_texts):
        if old != new:
            Run(run, None).text = new
    return True


def _iter_word_parts(doc) -> Iterable[Tuple[str, object]]:
    for part in doc.part.package.iter_parts():
        name = str(part.partname)
        if not name.startswith(_WORD_PARTS):
            continue
        element = getattr(part, "_element", None)
        if element is not None:
            yield name, element


def _zip_entries(path: str) -> List[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return []


class DocxHandler(BaseHandler):
    name = "docx"
    extensions = (".docx",)

    def _load(self, src: str):
        if Document is None:
            raise RuntimeError("缺少 python-docx 依赖，无法处理 .docx（请离线安装依赖）")
        return Document(src)

    def extract_text(self, src: str) -> str:
        doc = self._load(src)
        lines: List[str] = []
        for _, element in _iter_word_parts(doc):
            for paragraph in element.iter(qn("w:p")):
                text = _paragraph_text(paragraph)
                if text:
                    lines.append(text)
        return "\n".join(lines)

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        doc = self._load(src)
        processed_parts = set()
        for name, element in _iter_word_parts(doc):
            processed_parts.add(name)
            for paragraph in element.iter(qn("w:p")):
                _transform_paragraph(paragraph, transform)
            # 修订记录中的删除文本不可见，但仍保存在文件里，同样需要清理。
            for node in element.iter(qn("w:delText")):
                old = node.text or ""
                changes = transform(old)
                if changes:
                    node.text = apply_replacements(old, changes)

        warnings: List[str] = []
        entries = _zip_entries(src)
        if any(name.startswith("word/media/") for name in entries):
            warnings.append("文档内含图片，图片中的文字不会被 OCR 识别，请人工检查")
        if any(name.startswith("word/embeddings/") for name in entries):
            warnings.append("文档内含嵌入对象，嵌入内容未处理")
        comments = {"word/comments.xml", "word/commentsExtended.xml"}
        if comments.intersection(entries) and not any(
            name.endswith("comments.xml") for name in processed_parts
        ):
            warnings.append("文档含批注部件，但当前版本未能访问，请人工检查批注内容")

        if policy.strip_metadata:
            props = doc.core_properties
            props.author = ""
            props.last_modified_by = ""
            props.comments = ""
            props.category = ""
            props.subject = ""
            props.keywords = ""
            props.title = ""
            try:
                props.revision = 1
            except Exception:
                pass

        self._ensure_parent(dst)
        doc.save(dst)
        return warnings

    def can_restore(self) -> bool:
        return True
