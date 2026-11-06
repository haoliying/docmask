"""格式处理器基类与注册表。"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Type

from ..models import Policy, Replacement

Transformer = Callable[[str], List[Replacement]]

# 表格中的姓名列表头：这些列下方的内容按人名处理。
_PERSON_HEADER_WORDS = {
    "姓名",
    "名字",
    "人员",
    "人员姓名",
    "员工",
    "员工姓名",
    "职工",
    "成员",
    "成员姓名",
    "联系人",
    "负责人",
    "申请人",
    "收件人",
    "发件人",
    "客户姓名",
    "员工姓名",
    "患者姓名",
    "学生姓名",
    "经办人",
    "代理人",
    "法定代表人",
    "填报人",
    "制表人",
    "审核人",
    "审批人",
    "项目经理",
    "对接人",
    "开户人",
    "户名",
    "持卡人",
    "签字",
    "签名",
}

_PERSON_PROBE = "姓名:"


def is_person_header(value: object) -> bool:
    """判断单元格文本是否是姓名列表头（允许括号备注与空白）。"""
    if not isinstance(value, str):
        return False
    text = re.sub(r"\s+", "", value)
    text = re.sub(r"[（(][^）)]*[）)]", "", text).rstrip(":：")
    return text in _PERSON_HEADER_WORDS


def person_cell_changes(
    transform: Transformer, value: str
) -> List[Replacement]:
    """把姓名列中的裸人名转换为替换项。

    检测引擎依赖“姓名：”之类的标签，因此这里给单元格值补一个标签再检测，
    最后把偏移量还原到单元格自身。
    """
    if not value:
        return []
    # 单元格自带“姓名：张三”之类的标签时，直接按原文检测，避免重复加标签。
    if ":" in value or "：" in value:
        return transform(value)
    changes = transform(_PERSON_PROBE + value)
    offset = len(_PERSON_PROBE)
    result: List[Replacement] = []
    for item in changes:
        start = item.start - offset
        end = item.end - offset
        if end <= 0 or start >= len(value):
            continue
        result.append(
            Replacement(
                start=max(0, start),
                end=min(len(value), end),
                text=item.text,
                etype=item.etype,
            )
        )
    return result


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

    def adjust_destination(self, src: str, dst: str) -> str:
        """按文件实际内容调整输出路径，例如扩展名与实际格式不一致时。"""
        return dst

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
    from .xls_handler import XlsHandler
    from .pptx_handler import PptxHandler
    from .pdf_handler import PdfHandler

    for cls in (
        TextHandler,
        CsvHandler,
        JsonHandler,
        DocxHandler,
        XlsxHandler,
        XlsHandler,
        PptxHandler,
        PdfHandler,
    ):
        register(cls())
