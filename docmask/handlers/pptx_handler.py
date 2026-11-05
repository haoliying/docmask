"""PowerPoint (.pptx) 处理。"""

from __future__ import annotations

import zipfile
from typing import Iterator, List

from ..models import Policy, Replacement
from .base import BaseHandler, Transformer
from .runutils import redistribute_runs

try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except Exception:  # pragma: no cover
    Presentation = None  # type: ignore
    MSO_SHAPE_TYPE = None  # type: ignore


class PptxHandler(BaseHandler):
    name = "pptx"
    extensions = (".pptx",)

    def _load(self, src: str):
        if Presentation is None:
            raise RuntimeError("缺少 python-pptx 依赖，无法处理 .pptx（请离线安装依赖）")
        return Presentation(src)

    def _iter_shapes(self, shapes) -> Iterator[object]:
        for shape in shapes:
            yield shape
            if MSO_SHAPE_TYPE is not None and getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
                yield from self._iter_shapes(shape.shapes)

    def _transform_text_frame(self, text_frame, transform: Transformer) -> bool:
        changed = False
        for paragraph in text_frame.paragraphs:
            runs = list(paragraph.runs)
            if not runs:
                continue
            texts = [run.text or "" for run in runs]
            full = "".join(texts)
            if not full:
                continue
            changes: List[Replacement] = transform(full)
            if not changes:
                continue
            new_texts = redistribute_runs(texts, changes)
            for run, old, new in zip(runs, texts, new_texts):
                if old != new:
                    run.text = new
                    changed = True
        return changed

    def _iter_text_frames(self, slide) -> Iterator[object]:
        for shape in self._iter_shapes(slide.shapes):
            if getattr(shape, "has_text_frame", False):
                yield shape.text_frame
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        yield cell.text_frame

    def extract_text(self, src: str) -> str:
        prs = self._load(src)
        lines: List[str] = []
        for slide in prs.slides:
            for text_frame in self._iter_text_frames(slide):
                if text_frame.text:
                    lines.append(text_frame.text)
            if slide.has_notes_slide:
                notes = slide.notes_slide
                for text_frame in self._iter_text_frames(notes):
                    if text_frame.text:
                        lines.append(text_frame.text)
        return "\n".join(lines)

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        prs = self._load(src)
        picture_count = 0
        for slide in prs.slides:
            for shape in self._iter_shapes(slide.shapes):
                if MSO_SHAPE_TYPE is not None and getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE:
                    picture_count += 1
                if getattr(shape, "has_text_frame", False):
                    self._transform_text_frame(shape.text_frame, transform)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        for cell in row.cells:
                            self._transform_text_frame(cell.text_frame, transform)
            if slide.has_notes_slide:
                for text_frame in self._iter_text_frames(slide.notes_slide):
                    self._transform_text_frame(text_frame, transform)

        warnings: List[str] = []
        if picture_count:
            warnings.append(f"演示文稿含 {picture_count} 张图片，图片中的文字不会被 OCR 识别")
        try:
            with zipfile.ZipFile(src) as zf:
                names = zf.namelist()
            if any(name.startswith("ppt/comments/") for name in names):
                warnings.append("演示文稿含批注，当前版本未处理批注文本")
            if any(name.startswith("ppt/diagrams/") for name in names):
                warnings.append("演示文稿含 SmartArt，图形内文本未处理")
            if any(name.startswith("ppt/charts/") for name in names):
                warnings.append("演示文稿含图表，图表中的文本未处理")
        except (OSError, zipfile.BadZipFile):
            pass

        if policy.strip_metadata:
            props = prs.core_properties
            for attr in (
                "author",
                "last_modified_by",
                "title",
                "subject",
                "comments",
                "keywords",
                "category",
            ):
                try:
                    setattr(props, attr, "")
                except Exception:
                    pass
            try:
                props.revision = 1
            except Exception:
                pass

        self._ensure_parent(dst)
        prs.save(dst)
        return warnings
