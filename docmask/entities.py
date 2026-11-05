"""实体类型注册表：供 CLI、报告和 Web UI 共用。"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List

# 顺序即 Web UI 中的展示顺序。
ENTITY_DEFS: "OrderedDict[str, Dict[str, object]]" = OrderedDict(
    [
        (
            "PERSON",
            {
                "label": "人名",
                "group": "身份信息",
                "default": True,
                "description": "标签后的姓名、尊称，以及自定义姓名词表",
            },
        ),
        (
            "CN_ID",
            {
                "label": "身份证号",
                "group": "身份信息",
                "default": True,
                "description": "18 位居民身份证号（含校验位验证）",
            },
        ),
        (
            "PASSPORT",
            {
                "label": "护照/证件号",
                "group": "身份信息",
                "default": True,
                "description": "护照号标签及常见中国护照号码格式",
            },
        ),
        (
            "CN_MOBILE",
            {
                "label": "手机号",
                "group": "身份信息",
                "default": True,
                "description": "中国大陆 11 位手机号",
            },
        ),
        (
            "CN_LANDLINE",
            {
                "label": "固定电话",
                "group": "身份信息",
                "default": True,
                "description": "带区号的固定电话号码",
            },
        ),
        (
            "EMAIL",
            {
                "label": "邮箱地址",
                "group": "身份信息",
                "default": True,
                "description": "电子邮件地址",
            },
        ),
        (
            "ADDRESS",
            {
                "label": "地址",
                "group": "身份信息",
                "default": True,
                "description": "地址标签后的内容及常见省市区+道路门牌格式",
            },
        ),
        (
            "BANK_CARD",
            {
                "label": "银行卡号",
                "group": "财务信息",
                "default": True,
                "description": "16-19 位银行卡号（Luhn 校验）",
            },
        ),
        (
            "ACCOUNT",
            {
                "label": "账号",
                "group": "财务信息",
                "default": True,
                "description": "账号、微信号、QQ 号等标签后的内容",
            },
        ),
        (
            "ORG",
            {
                "label": "机构名称",
                "group": "机构与地点",
                "default": True,
                "description": "公司/集团/大学/医院等机构名称及标签内容",
            },
        ),
        (
            "PATTERN_ADDRESS",
            {
                "label": "结构化地址",
                "group": "机构与地点",
                "default": True,
                "description": "省市区 + 道路 + 门牌号格式",
            },
        ),
        (
            "CN_LICENSE_PLATE",
            {
                "label": "车牌号",
                "group": "机构与地点",
                "default": True,
                "description": "中国民用机动车号牌",
            },
        ),
        (
            "SOCIAL_CREDIT_CODE",
            {
                "label": "统一社会信用代码",
                "group": "机构与地点",
                "default": False,
                "description": "18 位统一社会信用代码（含校验位验证）",
            },
        ),
        (
            "IPV4",
            {
                "label": "IP 地址",
                "group": "网络与凭证",
                "default": True,
                "description": "IPv4 地址",
            },
        ),
        (
            "API_KEY",
            {
                "label": "API Key / Token",
                "group": "网络与凭证",
                "default": True,
                "description": "常见 API Key、JWT、访问令牌格式",
            },
        ),
        (
            "PASSWORD",
            {
                "label": "密码字段",
                "group": "网络与凭证",
                "default": True,
                "description": "密码/口令/secret 等标签后的内容",
            },
        ),
        (
            "URL",
            {
                "label": "URL",
                "group": "网络与凭证",
                "default": False,
                "description": "带协议的链接（可能包含内部域名）",
            },
        ),
        (
            "CUSTOM",
            {
                "label": "自定义敏感词",
                "group": "自定义",
                "default": True,
                "description": "用户词表中的词语或项目名",
            },
        ),
    ]
)

DEFAULT_ENABLED = {k for k, v in ENTITY_DEFS.items() if v["default"]}

# 占位符前缀。使用 ASCII，保证在 PDF / 表格 / 代码中安全。
TOKEN_PREFIX: Dict[str, str] = {
    "PERSON": "NAME",
    "CN_ID": "ID",
    "PASSPORT": "PASSPORT",
    "CN_MOBILE": "MOBILE",
    "CN_LANDLINE": "TEL",
    "EMAIL": "EMAIL",
    "ADDRESS": "ADDR",
    "PATTERN_ADDRESS": "ADDR",
    "BANK_CARD": "BANK",
    "ACCOUNT": "ACCOUNT",
    "ORG": "ORG",
    "CN_LICENSE_PLATE": "PLATE",
    "SOCIAL_CREDIT_CODE": "USCC",
    "IPV4": "IP",
    "API_KEY": "APIKEY",
    "PASSWORD": "PWD",
    "URL": "URL",
    "CUSTOM": "CUSTOM",
}

# 部分保留策略的默认前后保留长度（按类型）。
PARTIAL_KEEP = {
    "CN_MOBILE": (3, 4),
    "CN_ID": (6, 4),
    "PASSPORT": (2, 3),
    "BANK_CARD": (4, 4),
    "CN_LANDLINE": (4, 3),
    "PERSON": (1, 0),
    "ADDRESS": (6, 0),
    "PATTERN_ADDRESS": (6, 0),
    "ORG": (2, 0),
    "ACCOUNT": (2, 2),
    "CN_LICENSE_PLATE": (2, 1),
    "IPV4": (4, 0),
    "URL": (8, 0),
    "CUSTOM": (1, 0),
}

# 检测冲突时的优先级：数值越大越优先。
PRIORITY = {
    "PASSWORD": 100,
    "ADDRESS": 96,
    "PATTERN_ADDRESS": 95,
    "PERSON": 94,
    "ACCOUNT": 93,
    "ORG": 92,
    "CN_ID": 90,
    "PASSPORT": 89,
    "API_KEY": 88,
    "BANK_CARD": 85,
    "SOCIAL_CREDIT_CODE": 84,
    "EMAIL": 82,
    "CN_MOBILE": 80,
    "CN_LANDLINE": 78,
    "CN_LICENSE_PLATE": 70,
    "IPV4": 65,
    "URL": 60,
    "CUSTOM": 75,
}


def label_of(etype: str) -> str:
    item = ENTITY_DEFS.get(etype)
    if item:
        return str(item["label"])
    return etype


def entity_list() -> List[Dict[str, object]]:
    return [
        {
            "type": key,
            "label": value["label"],
            "group": value["group"],
            "default": value["default"],
            "description": value["description"],
            "token_prefix": TOKEN_PREFIX.get(key, key),
        }
        for key, value in ENTITY_DEFS.items()
    ]
