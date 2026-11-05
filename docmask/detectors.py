"""敏感信息检测引擎。

设计原则：
- 全部在本地完成，不依赖任何在线服务或模型下载。
- 校验优先：身份证、银行卡、统一社会信用代码都做校验，降低误报。
- 上下文优先：姓名、地址、机构、账号等中文实体依赖标签或格式特征。
- 冲突消解：同一段文本被多个规则命中时，按优先级与覆盖长度选择。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Pattern, Sequence, Tuple

from .entities import PRIORITY
from .models import Match, Policy
from .validators import cn_id_valid, ipv4_valid, luhn_valid, uscc_valid

_CN = r"\u4e00-\u9fa5"

# 常见中文姓氏，用于“尊称式”人名识别。
_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平"
    "黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝"
    "董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊"
    "胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉"
    "钮龚程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌"
    "焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘"
    "景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阴"
    "胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕"
    "冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居"
    "衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷"
    "訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)

_STOP_PERSON = {
    "姓名",
    "名字",
    "签字",
    "签名",
    "日期",
    "电话",
    "手机",
    "手机号",
    "手机号码",
    "联系电话",
    "邮箱",
    "邮箱地址",
    "地址",
    "身份证号",
    "证件号",
    "银行卡号",
    "卡号",
    "账号",
    "单位",
    "单位名称",
    "公司",
    "公司名称",
    "部门",
    "职务",
    "号码",
    "无",
    "空白",
    "本人",
    "本人签字",
    "经办人",
    "负责人",
    "联系人",
    "申请人",
    "收件人",
    "发件人",
    "甲方",
    "乙方",
}

# 已经是占位符的文本不再重复检测。
_PLACEHOLDER_RE = re.compile(r"^\[[A-Z][A-Z0-9_]{0,20}_\d{3,}\]$")


@dataclass
class _Rule:
    etype: str
    pattern: Pattern[str]
    priority: int
    confidence: float
    group: int = 0
    validator: str = ""
    detector: str = "regex"


class DetectionEngine:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.enabled = set(policy.enabled)
        self.rules = self._compile_custom_rules(policy.custom_patterns)
        self._custom_words = self._prepare_words(policy.custom_words)

    # ------------------------------------------------------------------ public
    def detect(self, text: str) -> List[Match]:
        if not text:
            return []
        matches: List[Match] = []
        matches.extend(self._detect_emails(text))
        matches.extend(self._detect_phones(text))
        matches.extend(self._detect_ids(text))
        matches.extend(self._detect_bank_cards(text))
        matches.extend(self._detect_ipv4(text))
        matches.extend(self._detect_plates(text))
        matches.extend(self._detect_passports(text))
        matches.extend(self._detect_social_credit(text))
        matches.extend(self._detect_api_keys(text))
        matches.extend(self._detect_passwords(text))
        matches.extend(self._detect_urls(text))
        matches.extend(self._detect_person(text))
        matches.extend(self._detect_address(text))
        matches.extend(self._detect_org(text))
        matches.extend(self._detect_accounts(text))
        matches.extend(self._detect_custom_words(text))
        matches.extend(self._detect_custom_patterns(text))
        return _select_non_overlapping(matches)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _prepare_words(words: Dict[str, List[str]]) -> List[Tuple[str, Pattern[str]]]:
        prepared: List[Tuple[str, Pattern[str]]] = []
        for etype, items in (words or {}).items():
            for word in items or []:
                word = str(word).strip()
                if len(word) < 2:
                    continue
                escaped = re.escape(word)
                if re.fullmatch(r"[\x00-\x7f]+", word):
                    pattern = re.compile(
                        r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])",
                        re.IGNORECASE,
                    )
                else:
                    pattern = re.compile(escaped)
                prepared.append((etype or "CUSTOM", pattern))
        # 长词优先，避免短词抢先覆盖
        prepared.sort(key=lambda item: -len(item[1].pattern))
        return prepared

    @staticmethod
    def _compile_custom_rules(rules: Sequence[Dict[str, object]]) -> List[_Rule]:
        compiled: List[_Rule] = []
        for idx, rule in enumerate(rules or []):
            if not isinstance(rule, dict):
                raise ValueError(f"自定义规则 #{idx + 1} 必须是对象")
            if rule.get("enabled", True) is False:
                continue
            pattern = rule.get("pattern")
            if not pattern:
                raise ValueError(f"自定义规则 #{idx + 1} 缺少 pattern")
            flags = re.IGNORECASE if rule.get("ignore_case", False) else 0
            try:
                compiled_pattern = re.compile(str(pattern), flags)
            except re.error as exc:
                raise ValueError(f"自定义规则 #{idx + 1} 正则无效: {exc}") from exc
            etype = str(rule.get("type") or "CUSTOM").upper()
            validator = str(rule.get("validator", ""))
            if validator and validator not in {"luhn", "cn_id", "uscc", "ipv4"}:
                raise ValueError(f"自定义规则 #{idx + 1} 的 validator 无效: {validator}")
            compiled.append(
                _Rule(
                    etype=etype,
                    pattern=compiled_pattern,
                    priority=int(rule.get("priority", PRIORITY.get(etype, 75))),
                    confidence=float(rule.get("confidence", 0.95)),
                    group=int(rule.get("group", 0)),
                    validator=validator,
                    detector="custom_regex",
                )
            )
        return compiled

    @staticmethod
    def _is_usable(value: str) -> bool:
        value = value.strip()
        if len(value) < 2:
            return False
        if _PLACEHOLDER_RE.match(value):
            return False
        if value and all(ch in "*＊#●■□" for ch in value):
            return False
        return True

    def _add(
        self,
        out: List[Match],
        text: str,
        start: int,
        end: int,
        etype: str,
        confidence: float,
        detector: str,
        priority: Optional[int] = None,
    ) -> None:
        while start < end and text[start] in " \t\r\n\"'“”‘’":
            start += 1
        while end > start and text[end - 1] in " \t\r\n\"'“”‘’":
            end -= 1
        if start >= end:
            return
        value = text[start:end]
        if not self._is_usable(value):
            return
        out.append(
            Match(
                start=start,
                end=end,
                etype=etype,
                value=value,
                confidence=confidence,
                priority=priority if priority is not None else PRIORITY.get(etype, 50),
                detector=detector,
            )
        )

    def _iter_group(
        self,
        text: str,
        pattern: Pattern[str],
        etype: str,
        group: int = 0,
        confidence: float = 0.9,
        detector: str = "regex",
        validator: str = "",
        priority: Optional[int] = None,
    ) -> Iterable[Tuple[int, int, float, int]]:
        for match in pattern.finditer(text):
            try:
                start, end = match.span(group)
            except IndexError:
                continue
            value = text[start:end]
            if validator:
                if validator == "luhn" and not luhn_valid(value):
                    continue
                if validator == "cn_id" and not cn_id_valid(value):
                    continue
                if validator == "uscc" and not uscc_valid(value):
                    continue
                if validator == "ipv4" and not ipv4_valid(value):
                    continue
            if not self._is_usable(value):
                continue
            yield start, end, confidence, priority or PRIORITY.get(etype, 50)

    # --------------------------------------------------------------- detectors
    def _detect_emails(self, text: str) -> List[Match]:
        if "EMAIL" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(
            r"(?<![A-Za-z0-9._%+\-])"
            r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+"
        )
        for match in pattern.finditer(text):
            value = match.group(0)
            if value.endswith(".jpg") or value.endswith(".png"):
                continue
            self._add(out, text, match.start(), match.end(), "EMAIL", 0.97, "email_regex")
        return out

    def _detect_phones(self, text: str) -> List[Match]:
        out: List[Match] = []
        if "CN_MOBILE" in self.enabled:
            pattern = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
            for match in pattern.finditer(text):
                self._add(out, text, match.start(), match.end(), "CN_MOBILE", 0.96, "mobile_regex")
        if "CN_LANDLINE" in self.enabled:
            pattern = re.compile(r"(?<!\d)(?:\(?0\d{2,3}\)?[- ]?)\d{7,8}(?!\d)")
            for match in pattern.finditer(text):
                self._add(out, text, match.start(), match.end(), "CN_LANDLINE", 0.9, "landline_regex")
        return out

    def _detect_ids(self, text: str) -> List[Match]:
        if "CN_ID" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
        for match in pattern.finditer(text):
            value = match.group(0)
            if cn_id_valid(value):
                self._add(out, text, match.start(), match.end(), "CN_ID", 0.99, "cn_id_checksum")
            else:
                # 校验失败但形如身份证（含合理出生日期段）仍按高风险处理，避免漏脱敏。
                try:
                    year = int(value[6:10])
                    month = int(value[10:12])
                    day = int(value[12:14])
                    plausible = 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
                except ValueError:
                    plausible = False
                if plausible:
                    self._add(out, text, match.start(), match.end(), "CN_ID", 0.6, "cn_id_shape")
        return out

    def _detect_bank_cards(self, text: str) -> List[Match]:
        if "BANK_CARD" not in self.enabled:
            return []
        out: List[Match] = []
        patterns = (
            re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
            re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{4}(?:[ -]?\d{1,3})?(?!\d)"),
        )
        seen = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group(0)
                key = (match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                if luhn_valid(value):
                    self._add(
                        out, text, match.start(), match.end(), "BANK_CARD", 0.94, "bank_luhn"
                    )
        # 有明确“卡号”标签时，即使校验位不合法也按银行卡处理，避免漏脱敏。
        labeled = re.compile(
            r"(?:银行卡号|信用卡号|储蓄卡号|卡\s*号)\s*[:：]?\s*"
            r"((?:\d[ -]?){12,19}\d)"
        )
        for match in labeled.finditer(text):
            digits = re.sub(r"\D", "", match.group(1))
            if 13 <= len(digits) <= 19:
                self._add(
                    out,
                    text,
                    match.start(1),
                    match.end(1),
                    "BANK_CARD",
                    0.9,
                    "bank_label",
                )
        return out

    def _detect_ipv4(self, text: str) -> List[Match]:
        if "IPV4" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(
            r"(?<![\d.])"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}"
            r"(?![\d.])"
        )
        for match in pattern.finditer(text):
            if ipv4_valid(match.group(0)):
                self._add(out, text, match.start(), match.end(), "IPV4", 0.9, "ipv4_regex")
        return out

    def _detect_plates(self, text: str) -> List[Match]:
        if "CN_LICENSE_PLATE" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(
            r"(?<![A-Za-z0-9])"
            r"([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]"
            r"[A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6})(?![A-Za-z0-9])"
        )
        for match in pattern.finditer(text):
            self._add(
                out,
                text,
                match.start(),
                match.end(),
                "CN_LICENSE_PLATE",
                0.92,
                "plate_regex",
            )
        return out

    def _detect_passports(self, text: str) -> List[Match]:
        if "PASSPORT" not in self.enabled:
            return []
        out: List[Match] = []
        labeled = re.compile(
            r"(?:护照(?:号码|号)?|港澳通行证(?:号码|号)?|台胞证(?:号码|号)?|通行证号码)"
            r"[ \t]*[:：]?[ \t]*([A-Za-z0-9]{5,20})"
        )
        for match in labeled.finditer(text):
            self._add(
                out,
                text,
                match.start(1),
                match.end(1),
                "PASSPORT",
                0.92,
                "passport_label",
            )
        strict = re.compile(r"(?<![A-Za-z0-9])[EG]\d{8}(?![A-Za-z0-9])")
        for match in strict.finditer(text):
            self._add(
                out, text, match.start(), match.end(), "PASSPORT", 0.72, "passport_regex"
            )
        return out

    def _detect_social_credit(self, text: str) -> List[Match]:
        if "SOCIAL_CREDIT_CODE" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(r"(?<![0-9A-Za-z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Za-z])")
        for match in pattern.finditer(text):
            if uscc_valid(match.group(0)):
                self._add(
                    out,
                    text,
                    match.start(),
                    match.end(),
                    "SOCIAL_CREDIT_CODE",
                    0.97,
                    "uscc_checksum",
                )
        return out

    def _detect_api_keys(self, text: str) -> List[Match]:
        if "API_KEY" not in self.enabled:
            return []
        out: List[Match] = []
        patterns = (
            re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}"),
            re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
            re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}"),
            re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}"),
            re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9\-]{10,}"),
            re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{30,}"),
            re.compile(
                r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
                r"\.[A-Za-z0-9_\-]{8,}"
            ),
        )
        for pattern in patterns:
            for match in pattern.finditer(text):
                self._add(
                    out, text, match.start(), match.end(), "API_KEY", 0.95, "api_key_regex"
                )
        labeled = re.compile(
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|token)"
            r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-\.]{8,})",
            re.IGNORECASE,
        )
        for match in labeled.finditer(text):
            self._add(
                out,
                text,
                match.start(1),
                match.end(1),
                "API_KEY",
                0.9,
                "api_key_label",
            )
        return out

    def _detect_passwords(self, text: str) -> List[Match]:
        if "PASSWORD" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(
            r"(?:密码|口令|passwd|password|pwd)\s*[:：=]\s*[\"']?"
            r"([^\s,;，；\"'<>]{3,64})",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            self._add(
                out, text, match.start(1), match.end(1), "PASSWORD", 0.95, "password_label"
            )
        return out

    def _detect_urls(self, text: str) -> List[Match]:
        if "URL" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(r"https?://[^\s<>\"'）)】\]]+")
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(".,;，。；")
            self._add(out, text, match.start(), match.start() + len(value), "URL", 0.85, "url_regex")
        return out

    def _detect_person(self, text: str) -> List[Match]:
        if "PERSON" not in self.enabled:
            return []
        out: List[Match] = []
        labels = re.compile(
            r"(?:姓\s*名|名\s*字|联系人|负责人|申请人|收件人|发件人|签\s*字|签\s*名|"
            r"开户人|户\s*名|持卡人|患者姓名|员工姓名|学生姓名|客户姓名|经办人|代理人|"
            r"法定代表(?:人)?|填报人|制表人|审核人|审批人|项目经理|对接人)"
            r"[ \t]*[:：]?[ \t]*([\u4e00-\u9fa5·]{2,8})"
        )
        for match in labels.finditer(text):
            value = text[match.start(1) : match.end(1)]
            if value in _STOP_PERSON or any(stop in value for stop in ("签字", "签名", "日期")):
                continue
            self._add(
                out, text, match.start(1), match.end(1), "PERSON", 0.9, "person_label"
            )

        honorific = re.compile(
            r"(["
            + _SURNAMES
            + r"][\u4e00-\u9fa5]{0,2})(?:先生|女士|小姐|同志|老师|医生|律师|"
            r"经理|总监|主任|主管|师傅|教授|院士)"
        )
        for match in honorific.finditer(text):
            self._add(
                out, text, match.start(1), match.end(1), "PERSON", 0.78, "person_honorific"
            )

        english = re.compile(
            r"(?:Name|Contact|Applicant|Recipient|Sender|Customer|Patient)"
            r"\s*[:：]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"
        )
        for match in english.finditer(text):
            self._add(
                out, text, match.start(1), match.end(1), "PERSON", 0.85, "person_label_en"
            )
        return out

    def _detect_address(self, text: str) -> List[Match]:
        if "ADDRESS" not in self.enabled and "PATTERN_ADDRESS" not in self.enabled:
            return []
        out: List[Match] = []
        if "ADDRESS" in self.enabled:
            labels = re.compile(
                r"(?:地址|住址|家庭住址|通讯地址|收货地址|办公地址|注册地址|联系地址|"
                r"现住址|户籍地址|所在地)\s*[:：]\s*([^\n，。；;]{4,100})"
            )
            for match in labels.finditer(text):
                self._add(
                    out, text, match.start(1), match.end(1), "ADDRESS", 0.93, "address_label"
                )
        if "PATTERN_ADDRESS" in self.enabled:
            pattern = re.compile(
                r"(?<![A-Za-z0-9])"
                r"(?:(?:[\u4e00-\u9fa5]{2,8}(?:省|自治区|特别行政区))?)"
                r"(?:[\u4e00-\u9fa5]{2,8}市)?"
                r"(?:[\u4e00-\u9fa5]{2,8}(?:区|县))"
                r"[\u4e00-\u9fa5A-Za-z0-9\-]{2,30}?"
                r"(?:路|街|道|巷|胡同|大道)"
                r"[\u4e00-\u9fa5A-Za-z0-9\-]{0,20}?"
                r"\d{1,5}号"
                r"(?:[\u4e00-\u9fa5A-Za-z0-9\-]{0,20}(?:室|楼|层|单元|栋))?"
            )
            for match in pattern.finditer(text):
                self._add(
                    out,
                    text,
                    match.start(),
                    match.end(),
                    "PATTERN_ADDRESS",
                    0.8,
                    "address_pattern",
                )
        return out

    def _detect_org(self, text: str) -> List[Match]:
        if "ORG" not in self.enabled:
            return []
        out: List[Match] = []
        labels = re.compile(
            r"(?:公司名称|单位名称|企业名称|机构名称|学校名称|医院名称|工作单位|"
            r"所属单位|开户行|开户银行|公司|单位)[ \t]*[:：][ \t]*([^\n，。；;]{2,60})"
        )
        for match in labels.finditer(text):
            value = text[match.start(1) : match.end(1)]
            if value in {"无", "个人", "其他"}:
                continue
            self._add(out, text, match.start(1), match.end(1), "ORG", 0.92, "org_label")

        suffix = re.compile(
            r"(?:^|[\s，。；：、（）()《》\"'“”‘’]|(?:与|和|向|由|在|为|被|及|同|跟|给|对))"
            r"([\u4e00-\u9fa5A-Za-z0-9（）()·]{2,40}?"
            r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|集团|"
            r"大学(?![生路])|学院(?![路])|医院|研究院|事务所|协会|基金会|银行))"
        )
        for match in suffix.finditer(text):
            self._add(
                out, text, match.start(1), match.end(1), "ORG", 0.72, "org_suffix"
            )
        return out

    def _detect_accounts(self, text: str) -> List[Match]:
        if "ACCOUNT" not in self.enabled:
            return []
        out: List[Match] = []
        pattern = re.compile(
            r"(?:账号|帐号|账户|帐户|对公账号|收款账号|支付宝(?:账号)?|"
            r"微信号|微信|QQ号|QQ|邮箱账号|登录名|用户名)"
            r"[ \t]*[:：]?[ \t]*([A-Za-z0-9_\-@.]{4,64})"
        )
        for match in pattern.finditer(text):
            self._add(
                out, text, match.start(1), match.end(1), "ACCOUNT", 0.9, "account_label"
            )
        return out

    def _detect_custom_words(self, text: str) -> List[Match]:
        if "CUSTOM" not in self.enabled and not self._custom_words:
            return []
        out: List[Match] = []
        for etype, pattern in self._custom_words:
            if etype not in self.enabled and etype != "CUSTOM":
                continue
            for match in pattern.finditer(text):
                self._add(
                    out,
                    text,
                    match.start(),
                    match.end(),
                    etype,
                    0.96,
                    "custom_word",
                    priority=PRIORITY.get(etype, PRIORITY["CUSTOM"]),
                )
        return out

    def _detect_custom_patterns(self, text: str) -> List[Match]:
        out: List[Match] = []
        for rule in self.rules:
            # 规则文件中显式配置的正则始终执行
            for match in rule.pattern.finditer(text):
                try:
                    start, end = match.span(rule.group)
                except IndexError:
                    continue
                value = text[start:end]
                if rule.validator:
                    ok = {
                        "luhn": luhn_valid,
                        "cn_id": cn_id_valid,
                        "uscc": uscc_valid,
                        "ipv4": ipv4_valid,
                    }.get(rule.validator)
                    if ok is None:
                        raise ValueError(f"未知校验器: {rule.validator}")
                    if not ok(value):
                        continue
                self._add(
                    out,
                    text,
                    start,
                    end,
                    rule.etype,
                    rule.confidence,
                    rule.detector,
                    priority=rule.priority,
                )
        return out


def _select_non_overlapping(matches: List[Match]) -> List[Match]:
    """按优先级、长度、置信度贪心选择互不重叠的命中。"""
    if not matches:
        return []
    # 同一区间只保留最优的一条
    best: Dict[Tuple[int, int], Match] = {}
    for item in matches:
        key = (item.start, item.end)
        current = best.get(key)
        if current is None or (item.priority, item.confidence) > (
            current.priority,
            current.confidence,
        ):
            best[key] = item
    candidates = list(best.values())
    candidates.sort(
        key=lambda m: (-m.priority, -m.length, -m.confidence, m.start, m.end)
    )
    selected: List[Match] = []
    occupied: List[Tuple[int, int]] = []
    for item in candidates:
        conflict = False
        for start, end in occupied:
            if not (item.end <= start or item.start >= end):
                conflict = True
                break
        if conflict:
            continue
        selected.append(item)
        occupied.append((item.start, item.end))
    selected.sort(key=lambda m: (m.start, m.end))
    return selected
