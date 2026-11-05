"""规则文件、词表与策略组装。"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .entities import DEFAULT_ENABLED, ENTITY_DEFS
from .models import Policy


def load_rules_file(path: str) -> Dict[str, object]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"规则文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"规则文件 JSON 格式错误: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("规则文件根节点必须是 JSON 对象")
    return data


_WORD_ALIASES = {
    "姓名": "PERSON",
    "名字": "PERSON",
    "人名": "PERSON",
    "公司": "ORG",
    "单位": "ORG",
    "机构": "ORG",
    "公司名称": "ORG",
    "单位名称": "ORG",
    "手机": "CN_MOBILE",
    "手机号": "CN_MOBILE",
    "手机号码": "CN_MOBILE",
    "邮箱": "EMAIL",
    "邮箱地址": "EMAIL",
    "地址": "ADDRESS",
    "住址": "ADDRESS",
    "身份证": "CN_ID",
    "身份证号": "CN_ID",
    "银行卡": "BANK_CARD",
    "银行卡号": "BANK_CARD",
    "卡号": "BANK_CARD",
    "账号": "ACCOUNT",
    "车牌": "CN_LICENSE_PLATE",
    "车牌号": "CN_LICENSE_PLATE",
    "关键词": "CUSTOM",
    "敏感词": "CUSTOM",
}


def _word_type(label: str) -> str:
    label = label.strip()
    if not label:
        return "CUSTOM"
    upper = label.upper()
    if upper in ENTITY_DEFS:
        return upper
    return _WORD_ALIASES.get(label, "")


def parse_word_lines(text: str) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        etype = "CUSTOM"
        word = line
        for sep in (":", "："):
            if sep in line:
                left, right = line.split(sep, 1)
                resolved = _word_type(left)
                if resolved:
                    etype = resolved
                    word = right.strip()
                break
        if len(word) < 2:
            continue
        result.setdefault(etype, []).append(word)
    return result


def load_words_file(path: str) -> Dict[str, List[str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"词表文件不存在: {path}")
    with open(path, "r", encoding="utf-8-sig") as fh:
        return parse_word_lines(fh.read())


def build_policy(
    rules: Optional[Dict[str, object]] = None,
    enabled: Optional[List[str]] = None,
    disabled: Optional[List[str]] = None,
    strategy: Optional[str] = None,
    mask_char: Optional[str] = None,
    keep_length: Optional[bool] = None,
    strip_metadata: Optional[bool] = None,
    pdf_mode: Optional[str] = None,
    salt: Optional[str] = None,
    custom_words: Optional[Dict[str, List[str]]] = None,
    custom_patterns: Optional[List[Dict[str, object]]] = None,
) -> Policy:
    rules = rules or {}
    if "enabled" in rules:
        raw_enabled = rules.get("enabled")
        if not isinstance(raw_enabled, (list, tuple, set)):
            raise ValueError("规则文件的 enabled 必须是数组")
        enabled_set = {str(item).upper() for item in raw_enabled}
    else:
        enabled_set = set(DEFAULT_ENABLED)
    if enabled is not None:
        enabled_set = {str(item).upper() for item in enabled}
    raw_disabled = rules.get("disabled", [])
    if raw_disabled and not isinstance(raw_disabled, (list, tuple, set)):
        raise ValueError("规则文件的 disabled 必须是数组")
    for item in list(disabled or []) + list(raw_disabled or []):
        enabled_set.discard(str(item).upper())

    words: Dict[str, List[str]] = {}
    raw_words = rules.get("custom_words", {})
    if isinstance(raw_words, dict):
        for etype, items in raw_words.items():
            if isinstance(items, str):
                items = items.splitlines()
            words[str(etype).upper()] = [str(w).strip() for w in items if str(w).strip()]
    for etype, items in (custom_words or {}).items():
        words.setdefault(str(etype).upper(), []).extend(items)
    # 去重且保持顺序
    words = {k: list(dict.fromkeys(v)) for k, v in words.items()}

    patterns = list(custom_patterns or [])
    raw_patterns = rules.get("custom_patterns", [])
    if isinstance(raw_patterns, list):
        patterns = list(raw_patterns) + patterns

    policy = Policy(
        enabled=enabled_set,
        strategy=strategy or str(rules.get("strategy", "mask")),
        mask_char=mask_char or str(rules.get("mask_char", "*")),
        keep_length=(
            keep_length
            if keep_length is not None
            else bool(rules.get("keep_length", False))
        ),
        strip_metadata=(
            strip_metadata
            if strip_metadata is not None
            else bool(rules.get("strip_metadata", True))
        ),
        pdf_mode=pdf_mode or str(rules.get("pdf_mode", "text")),
        salt=salt or (str(rules["salt"]) if rules.get("salt") else None),
        custom_words=words,
        custom_patterns=patterns,
    )
    policy.validate()
    return policy


def sample_rules() -> Dict[str, object]:
    return {
        "enabled": sorted(DEFAULT_ENABLED),
        "disabled": ["URL", "SOCIAL_CREDIT_CODE"],
        "strategy": "mask",
        "mask_char": "*",
        "keep_length": False,
        "strip_metadata": True,
        "pdf_mode": "text",
        "custom_words": {
            "PERSON": ["张三", "李四"],
            "ORG": ["某某科技有限公司"],
            "CUSTOM": ["项目代号-朱雀"],
        },
        "custom_patterns": [
            {
                "type": "EMPLOYEE_ID",
                "pattern": "EMP-\\d{6}",
                "group": 0,
                "priority": 80,
                "validator": "",
                "ignore_case": False,
                "enabled": True,
            }
        ],
    }
