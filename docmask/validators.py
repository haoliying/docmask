"""号码校验函数。"""

from __future__ import annotations

_CN_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CN_ID_CHECK = "10X98765432"
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def luhn_valid(value: str) -> bool:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits or len(digits) != len(value):
        return False
    total = 0
    parity = len(digits) % 2
    for idx, ch in enumerate(digits):
        n = ord(ch) - 48
        if idx % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def cn_id_valid(value: str) -> bool:
    value = value.strip()
    if len(value) != 18:
        return False
    body = value[:17]
    if not body.isdigit():
        return False
    check = value[17].upper()
    if check not in _CN_ID_CHECK:
        return False
    # 出生日期基本校验
    try:
        year = int(value[6:10])
        month = int(value[10:12])
        day = int(value[12:14])
    except ValueError:
        return False
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return False
    total = sum(int(body[i]) * _CN_ID_WEIGHTS[i] for i in range(17))
    return _CN_ID_CHECK[total % 11] == check


def uscc_valid(value: str) -> bool:
    """统一社会信用代码校验。"""
    value = value.strip().upper()
    if len(value) != 18 or any(ch not in _USCC_CHARS for ch in value):
        return False
    total = sum(_USCC_CHARS.index(value[i]) * _USCC_WEIGHTS[i] for i in range(17))
    check = 31 - total % 31
    if check == 31:
        check = 0
    return _USCC_CHARS[check] == value[17]


def ipv4_valid(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part[0] == "0"):
            return False
        if not 0 <= int(part) <= 255:
            return False
    return True
