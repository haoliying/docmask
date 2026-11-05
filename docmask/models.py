"""核心数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Match:
    """文本中的一处敏感信息。"""

    start: int
    end: int
    etype: str
    value: str
    confidence: float = 0.9
    priority: int = 50
    detector: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start

    def as_public_dict(self, label: str = "") -> Dict[str, Any]:
        """用于报告/预览，不包含原文。"""
        return {
            "type": self.etype,
            "label": label or self.etype,
            "start": self.start,
            "end": self.end,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class Replacement:
    """一处将被替换的文本区间。text 为替换后的内容。"""

    start: int
    end: int
    text: str
    etype: str = ""


@dataclass
class Policy:
    """一次脱敏任务的策略。"""

    enabled: Set[str] = field(default_factory=set)
    strategy: str = "mask"  # mask | partial | replace | hash
    mask_char: str = "*"
    keep_length: bool = False
    strip_metadata: bool = True
    pdf_mode: str = "text"  # text | box
    salt: Optional[str] = None
    custom_words: Dict[str, List[str]] = field(default_factory=dict)
    custom_patterns: List[Dict[str, Any]] = field(default_factory=list)
    max_preview: int = 8

    def validate(self) -> None:
        if self.strategy not in {"mask", "partial", "replace", "hash"}:
            raise ValueError(f"未知脱敏策略: {self.strategy}")
        if self.pdf_mode not in {"text", "box"}:
            raise ValueError(f"未知 PDF 处理模式: {self.pdf_mode}")
        if not self.mask_char or len(self.mask_char) != 1:
            raise ValueError("mask_char 必须是单个字符")
        if self.mask_char in "<>\"'&\r\n\t":
            raise ValueError("mask_char 不能使用 < > \" ' & 或控制字符")


@dataclass
class FileOutcome:
    """单个文件的处理结果（用于报告，不含敏感原文）。"""

    source: str
    output: Optional[str] = None
    status: str = "ok"  # ok | error | skipped
    counts: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass
class JobSummary:
    files: List[FileOutcome] = field(default_factory=list)

    @property
    def total_entities(self) -> int:
        return sum(f.total for f in self.files)

    @property
    def counts(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for f in self.files:
            for k, v in f.counts.items():
                result[k] = result.get(k, 0) + v
        return dict(sorted(result.items(), key=lambda kv: (-kv[1], kv[0])))

    @property
    def ok_files(self) -> int:
        return sum(1 for f in self.files if f.status == "ok")

    @property
    def failed_files(self) -> int:
        return sum(1 for f in self.files if f.status == "error")


@dataclass
class PreviewItem:
    """预览项，只包含掩码后的上下文。"""

    type: str
    label: str
    preview: str
    confidence: float


@dataclass
class FilePreview:
    source: str
    counts: Dict[str, int]
    items: List[PreviewItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def total(self) -> int:
        return sum(self.counts.values())


ReplacementList = List[Replacement]
CountMap = Dict[str, int]
