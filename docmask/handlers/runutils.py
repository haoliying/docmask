"""把段落级替换结果重新分配到各个 run，尽量保留原有格式。"""

from __future__ import annotations

from typing import List, Sequence

from ..models import Replacement


def redistribute_runs(texts: Sequence[str], replacements: List[Replacement]) -> List[str]:
    if not replacements:
        return list(texts)
    full = "".join(texts)
    offsets = []
    cursor = 0
    for text in texts:
        offsets.append((cursor, cursor + len(text)))
        cursor += len(text)

    result: List[str] = []
    for run_text, (r_start, r_end) in zip(texts, offsets):
        if not any(rep.start < r_end and rep.end > r_start for rep in replacements):
            result.append(run_text)
            continue
        parts: List[str] = []
        cursor = r_start
        for rep in replacements:
            if rep.end <= r_start or rep.start >= r_end:
                continue
            overlap_start = max(rep.start, r_start)
            overlap_end = min(rep.end, r_end)
            if overlap_start > cursor:
                parts.append(full[cursor:overlap_start])
            # 替换文本只写入命中起点所在的 run，后续 run 只删除被覆盖的字符
            if rep.start >= r_start:
                parts.append(rep.text)
            cursor = max(cursor, overlap_end)
        if cursor < r_end:
            parts.append(full[cursor:r_end])
        result.append("".join(parts))
    return result
