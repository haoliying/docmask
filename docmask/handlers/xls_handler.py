"""Excel 97-2003 (.xls) 处理：xlrd 读取，xlwt 重建并写出。"""

from __future__ import annotations

import datetime
import zipfile
from typing import Dict, List, Set, Tuple

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import (
    BaseHandler,
    Transformer,
    is_person_header,
    person_cell_changes,
)

try:
    import xlrd
except Exception:  # pragma: no cover
    xlrd = None  # type: ignore

try:
    import xlwt
except Exception:  # pragma: no cover
    xlwt = None  # type: ignore

_DATE_STYLE = "YYYY-MM-DD"
_DATETIME_STYLE = "YYYY-MM-DD HH:MM:SS"


class XlsHandler(BaseHandler):
    name = "xls"
    extensions = (".xls",)

    @staticmethod
    def _is_ooxml(src: str) -> bool:
        """扩展名为 .xls 但内容其实是 xlsx（ZIP + xl/workbook.xml）时返回 True。"""
        try:
            with zipfile.ZipFile(src) as zf:
                return "xl/workbook.xml" in zf.namelist()
        except Exception:
            return False

    def adjust_destination(self, src: str, dst: str) -> str:
        if self._is_ooxml(src) and dst.lower().endswith(".xls"):
            return dst[:-4] + ".xlsx"
        return dst

    def _load(self, src: str):
        if xlrd is None:
            raise RuntimeError("缺少 xlrd 依赖，无法处理 .xls（请离线安装依赖）")
        try:
            return xlrd.open_workbook(src)
        except Exception as exc:
            raise RuntimeError(f"无法读取 .xls 文件：{exc}") from exc

    def extract_text(self, src: str) -> str:
        if self._is_ooxml(src):
            from .xlsx_handler import XlsxHandler

            return XlsxHandler().extract_text(src)
        book = self._load(src)
        lines: List[str] = []
        for sheet in book.sheets():
            person_columns = self._person_columns(sheet)
            for row in range(sheet.nrows):
                for col in range(sheet.ncols):
                    cell = sheet.cell(row, col)
                    if cell.ctype == xlrd.XL_CELL_TEXT and isinstance(cell.value, str):
                        if col in person_columns and row > person_columns[col]:
                            lines.append("姓名:" + cell.value)
                        else:
                            lines.append(cell.value)
        return "\n".join(lines)

    @staticmethod
    def _person_columns(sheet) -> Dict[int, int]:
        """返回“姓名”列表头所在的列索引（0 起）与该表头所在行。"""
        columns: Dict[int, int] = {}
        if xlrd is None:
            return columns
        for row in range(sheet.nrows):
            for col in range(sheet.ncols):
                cell = sheet.cell(row, col)
                if cell.ctype == xlrd.XL_CELL_TEXT and is_person_header(cell.value):
                    columns[col] = min(columns.get(col, row), row)
        return columns

    @staticmethod
    def _sheet_name(name: str, index: int) -> str:
        cleaned = "".join(ch for ch in str(name or "") if ch not in "[]:*?/\\")[:31]
        return cleaned or f"Sheet{index + 1}"

    @staticmethod
    def _merged_layout(sheet) -> Tuple[Dict[Tuple[int, int], Tuple[int, int]], Set[Tuple[int, int]]]:
        """返回合并区左上角坐标 -> 右下角坐标，以及需要跳过写入的坐标集合。"""
        anchors: Dict[Tuple[int, int], Tuple[int, int]] = {}
        covered: Set[Tuple[int, int]] = set()
        for rlo, rhi, clo, chi in getattr(sheet, "merged_cells", []) or []:
            row_end = max(rlo, rhi - 1)
            col_end = max(clo, chi - 1)
            anchors[(rlo, clo)] = (row_end, col_end)
            for row in range(rlo, row_end + 1):
                for col in range(clo, col_end + 1):
                    covered.add((row, col))
        return anchors, covered

    def _cell_value(
        self,
        book,
        cell,
        transform: Transformer,
        warnings: List[str],
        person: bool = False,
    ):
        ctype = cell.ctype
        value = cell.value
        if ctype == xlrd.XL_CELL_TEXT:
            if person:
                changes: List[Replacement] = person_cell_changes(transform, value)
            else:
                changes = transform(value)
            return apply_replacements(value, changes) if changes else value
        if ctype == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate_as_datetime(value, book.datemode)
            except Exception:
                warnings.append("存在无法解析的日期单元格，已按原值写入")
                return value
        if ctype == xlrd.XL_CELL_BOOLEAN:
            return bool(value)
        if ctype == xlrd.XL_CELL_ERROR:
            return None
        return value

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        if self._is_ooxml(src):
            from .xlsx_handler import XlsxHandler

            warnings = XlsxHandler().process(src, dst, transform, policy)
            warnings.insert(
                0,
                "文件扩展名为 .xls，但实际是 .xlsx 格式，已按 .xlsx 脱敏并输出 .xlsx",
            )
            return warnings
        if xlwt is None:
            raise RuntimeError("缺少 xlwt 依赖，无法写出 .xls（请离线安装依赖）")
        book = self._load(src)
        output = xlwt.Workbook(encoding="utf-8")
        date_style = xlwt.easyxf(num_format_str=_DATE_STYLE)
        datetime_style = xlwt.easyxf(num_format_str=_DATETIME_STYLE)
        warnings: List[str] = []

        for index, sheet in enumerate(book.sheets()):
            ws = output.add_sheet(self._sheet_name(sheet.name, index))
            anchors, covered = self._merged_layout(sheet)
            person_columns = self._person_columns(sheet)
            for row in range(sheet.nrows):
                for col in range(sheet.ncols):
                    position = (row, col)
                    if position in covered and position not in anchors:
                        continue
                    value = self._cell_value(
                        book,
                        sheet.cell(row, col),
                        transform,
                        warnings,
                        person=col in person_columns and row > person_columns[col],
                    )
                    if position in anchors:
                        row_end, col_end = anchors[position]
                        merged = "" if value is None else value
                        try:
                            ws.write_merge(row, row_end, col, col_end, merged)
                        except Exception:
                            if value is not None:
                                ws.write(row, col, value)
                        continue
                    if value is None:
                        continue
                    if isinstance(value, datetime.datetime):
                        if value.time() == datetime.time(0, 0):
                            ws.write(row, col, value.date(), date_style)
                        else:
                            ws.write(row, col, value, datetime_style)
                    else:
                        ws.write(row, col, value)

        warnings.append(
            "旧版 .xls 会按单元格内容重建：公式、样式、图表、图片与批注无法保留，建议优先使用 .xlsx"
        )
        self._ensure_parent(dst)
        output.save(dst)
        return warnings
