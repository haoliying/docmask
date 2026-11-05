"""CSV / TSV 处理。"""

from __future__ import annotations

import csv
import io
from typing import List

from ..masking import apply_replacements
from ..models import Policy, Replacement
from .base import BaseHandler, Transformer
from .textio import read_text_with_encoding, write_text_with_encoding


class CsvHandler(BaseHandler):
    name = "csv"
    extensions = (".csv", ".tsv")

    @staticmethod
    def _delimiter(text: str, ext: str) -> str:
        if ext == ".tsv":
            return "\t"
        sample = text[:8192]
        if sample.strip():
            try:
                return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                pass
        counts = {item: sample.count(item) for item in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","

    def extract_text(self, src: str) -> str:
        text, _ = read_text_with_encoding(src)
        return text

    def process(
        self, src: str, dst: str, transform: Transformer, policy: Policy
    ) -> List[str]:
        text, encoding = read_text_with_encoding(src)
        ext = src.lower().rsplit(".", 1)[-1]
        delimiter = self._delimiter(text, ext)
        reader = csv.reader(
            io.StringIO(text), delimiter=delimiter, quotechar='"', doublequote=True
        )
        output = io.StringIO(newline="")
        newline = "\r\n" if "\r\n" in text else "\n"
        writer = csv.writer(
            output,
            delimiter=delimiter,
            quotechar='"',
            doublequote=True,
            lineterminator=newline,
        )
        warnings: List[str] = []
        try:
            for row in reader:
                new_row = []
                for cell in row:
                    changes: List[Replacement] = transform(cell)
                    new_row.append(apply_replacements(cell, changes))
                writer.writerow(new_row)
        except csv.Error as exc:
            warnings.append(f"CSV 解析异常，已尽量保留内容: {exc}")
        write_text_with_encoding(dst, output.getvalue(), encoding)
        return warnings
