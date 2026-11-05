"""文本编码探测与读写。"""

from __future__ import annotations

import codecs
import os
from typing import Tuple

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def read_text_with_encoding(path: str) -> Tuple[str, str]:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return "", "utf-8"
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding), encoding
    for encoding in ("utf-8", "gb18030", "big5"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def write_text_with_encoding(path: str, text: str, encoding: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
