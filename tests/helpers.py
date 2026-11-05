"""测试辅助：构造合法号码与统一策略。"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from docmask.entities import DEFAULT_ENABLED
from docmask.models import Policy

_CN_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CN_ID_CHECK = "10X98765432"
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def make_cn_id(body: str = "11010519491231002") -> str:
    """由 17 位本体生成带合法校验位的身份证号。"""
    assert len(body) == 17 and body.isdigit()
    total = sum(int(body[i]) * _CN_ID_WEIGHTS[i] for i in range(17))
    return body + _CN_ID_CHECK[total % 11]


def make_uscc(body: str = "91330100MA2ABCDEF") -> str:
    """由 17 位本体生成带合法校验位的统一社会信用代码。"""
    assert len(body) == 17
    total = sum(_USCC_CHARS.index(body[i]) * _USCC_WEIGHTS[i] for i in range(17))
    check = 31 - total % 31
    if check == 31:
        check = 0
    return body + _USCC_CHARS[check]


def make_policy(
    strategy: str = "replace",
    enabled: Optional[Set[str]] = None,
    custom_words: Optional[Dict[str, List[str]]] = None,
    mask_char: str = "*",
    keep_length: bool = False,
    salt: Optional[str] = "test-salt",
    strip_metadata: bool = True,
) -> Policy:
    policy = Policy(
        enabled=set(DEFAULT_ENABLED) if enabled is None else set(enabled),
        strategy=strategy,
        mask_char=mask_char,
        keep_length=keep_length,
        strip_metadata=strip_metadata,
        salt=salt,
        custom_words=custom_words or {},
    )
    policy.validate()
    return policy
