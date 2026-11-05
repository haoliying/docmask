"""格式处理器基类与注册表。"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Type

from ..models import Policy, Replacement

Transformer = Callable[[str], List[Replacement]]


class BaseHandler:
    name = "base"
    extensions: tuple = ()

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        """处理 src，写入 dst，返回警告信息。"""
        raise NotImplementedError

    def extract_text(self, src: str) -> str:
        """提取可读文本，用于预览/统计。"""
        raise NotImplementedError

    def can_restore(self) -> bool:
        return True

    @staticmethod
    def _ensure_parent(dst: str) -> None:
        parent = os.path.dirname(os.path.abspath(dst))
        if parent:
            os.makedirs(parent, exist_ok=True)


_HANDLERS: List[BaseHandler] = []
_EXT_MAP: Dict[str, BaseHandler] = {}


def register(handler: BaseHandler) -> BaseHandler:
    _HANDLERS.append(handler)
    for ext in handler.extensions:
        _EXT_MAP[ext.lower()] = handler
    return handler


def get_handler(path: str) -> Optional[BaseHandler]:
    ext = os.path.splitext(path)[1].lower()
    return _EXT_MAP.get(ext)


def supported_extensions() -> List[str]:
    return sorted(_EXT_MAP)


def all_handlers() -> List[BaseHandler]:
    return list(_HANDLERS)


def load_builtin_handlers() -> None:
    if _HANDLERS:
        return
    from .text_handler import TextHandler
    from .csv_handler import CsvHandler
    from .json_handler import JsonHandler
    from .docx_handler import DocxHandler
    from .xlsx_handler import XlsxHandler
    from .pptx_handler import PptxHandler
    from .pdf_handler import PdfHandler

    for cls in (TextHandler, CsvHandler, JsonHandler, DocxHandler, XlsxHandler, PptxHandler, PdfHandler):
        register(cls())
