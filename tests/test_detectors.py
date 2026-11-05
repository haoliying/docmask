from __future__ import annotations

import unittest

from docmask.detectors import DetectionEngine
from tests.helpers import make_cn_id, make_policy


def types_of(text: str, **kwargs) -> list:
    policy = make_policy(enabled=kwargs.pop("enabled", None), **kwargs)
    return DetectionEngine(policy).detect(text)


class ContactDetectionTests(unittest.TestCase):
    def test_email_and_mobile(self) -> None:
        matches = types_of("请发送到 alice@example.com 或致电 13800138000。")
        found = {(m.etype, m.value) for m in matches}
        self.assertIn(("EMAIL", "alice@example.com"), found)
        self.assertIn(("CN_MOBILE", "13800138000"), found)

    def test_landline(self) -> None:
        matches = types_of("总机 010-12345678，传真 (021) 87654321。")
        values = {m.value for m in matches if m.etype == "CN_LANDLINE"}
        self.assertIn("010-12345678", values)

    def test_disabled_entity_is_skipped(self) -> None:
        matches = types_of("alice@example.com 13800138000", enabled={"EMAIL"})
        self.assertEqual({m.etype for m in matches}, {"EMAIL"})


class IdentityDetectionTests(unittest.TestCase):
    def test_cn_id_checksum(self) -> None:
        value = make_cn_id()
        matches = types_of(f"身份证号：{value}")
        self.assertTrue(any(m.etype == "CN_ID" and m.value == value for m in matches))

    def test_cn_id_plausible_shape(self) -> None:
        matches = types_of("身份证 110105194912310021")
        self.assertTrue(any(m.etype == "CN_ID" and m.confidence < 0.9 for m in matches))

    def test_person_label_and_honorific(self) -> None:
        matches = types_of("联系人：张三，张三先生负责此项目。")
        values = [m.value for m in matches if m.etype == "PERSON"]
        self.assertIn("张三", values)

    def test_person_header_does_not_span_newline(self) -> None:
        matches = types_of("姓名\n手机号\n张三")
        self.assertFalse([m for m in matches if m.etype == "PERSON"])

    def test_passport_label(self) -> None:
        matches = types_of("护照号码：E12345678")
        self.assertTrue(any(m.etype == "PASSPORT" and m.value == "E12345678" for m in matches))


class FinanceDetectionTests(unittest.TestCase):
    def test_bank_card_luhn(self) -> None:
        matches = types_of("卡号 4111111111111111")
        self.assertTrue(any(m.etype == "BANK_CARD" for m in matches))

    def test_bank_card_label_fallback(self) -> None:
        matches = types_of("银行卡号：6222020200112233445")
        self.assertTrue(any(m.etype == "BANK_CARD" for m in matches))

    def test_account_label(self) -> None:
        matches = types_of("微信号：alice_2026")
        self.assertTrue(any(m.etype == "ACCOUNT" and m.value == "alice_2026" for m in matches))


class NetworkDetectionTests(unittest.TestCase):
    def test_api_key_and_password(self) -> None:
        text = "api_key=sk-abcdefghijklmnopqrstuvwx\npassword: S3cretPass"
        matches = types_of(text)
        found = {m.etype for m in matches}
        self.assertIn("API_KEY", found)
        self.assertIn("PASSWORD", found)

    def test_ipv4_and_plate(self) -> None:
        matches = types_of("服务器 192.168.1.20，车辆 京A12345。")
        found = {m.etype for m in matches}
        self.assertIn("IPV4", found)
        self.assertIn("CN_LICENSE_PLATE", found)


class OrgAddressDetectionTests(unittest.TestCase):
    def test_org_label_and_suffix(self) -> None:
        matches = types_of("工作单位：某某科技有限公司；同时与北京某某医院合作。")
        values = [m.value for m in matches if m.etype == "ORG"]
        self.assertTrue(any("某某科技有限公司" in v for v in values))

    def test_address_label_wins_conflict(self) -> None:
        matches = types_of("地址：北京市朝阳区建国路88号")
        addresses = [m for m in matches if m.etype in {"ADDRESS", "PATTERN_ADDRESS"}]
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0].etype, "ADDRESS")
        self.assertEqual(addresses[0].value, "北京市朝阳区建国路88号")


class CustomRuleTests(unittest.TestCase):
    def test_custom_words(self) -> None:
        matches = types_of(
            "项目代号-朱雀即将启动。",
            custom_words={"CUSTOM": ["项目代号-朱雀"]},
        )
        self.assertTrue(any(m.etype == "CUSTOM" and m.value == "项目代号-朱雀" for m in matches))

    def test_ascii_word_boundary(self) -> None:
        policy = make_policy(custom_words={"CUSTOM": ["ACME"]})
        engine = DetectionEngine(policy)
        self.assertTrue(engine.detect("合作方 ACME 公司"))
        self.assertFalse(engine.detect("前缀XACMEY后缀"))

    def test_custom_regex_always_runs(self) -> None:
        policy = make_policy(
            enabled={"EMAIL"},
            custom_words=None,
        )
        policy.custom_patterns = [
            {"type": "EMPLOYEE_ID", "pattern": r"EMP-\d{6}", "priority": 88}
        ]
        engine = DetectionEngine(policy)
        matches = engine.detect("员工 EMP-123456 的邮箱 a@b.com")
        self.assertTrue(any(m.etype == "EMPLOYEE_ID" for m in matches))
        self.assertTrue(any(m.etype == "EMAIL" for m in matches))

    def test_placeholder_not_detected(self) -> None:
        self.assertEqual(types_of("[MOBILE_001] [NAME_002]"), [])

    def test_selection_is_non_overlapping(self) -> None:
        matches = types_of("邮箱 alice@example.com 电话 13800138000")
        ordered = sorted(matches, key=lambda m: m.start)
        for left, right in zip(ordered, ordered[1:]):
            self.assertLessEqual(left.end, right.start)


if __name__ == "__main__":
    unittest.main()
