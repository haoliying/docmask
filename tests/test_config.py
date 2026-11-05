from __future__ import annotations

import json
import os
import tempfile
import unittest

from docmask.config import (
    build_policy,
    load_rules_file,
    load_words_file,
    parse_word_lines,
    sample_rules,
)
from docmask.entities import DEFAULT_ENABLED


class WordListTests(unittest.TestCase):
    def test_aliases_and_plain_words(self) -> None:
        words = parse_word_lines(
            "# 注释\n"
            "姓名:张三\n"
            "公司：某某科技有限公司\n"
            "CUSTOM:项目代号-朱雀\n"
            "PERSON:李四\n"
            "手机号:13800138000\n"
            "孤立敏感词\n"
            "x\n"
        )
        self.assertEqual(words["PERSON"], ["张三", "李四"])
        self.assertEqual(words["ORG"], ["某某科技有限公司"])
        self.assertEqual(words["CUSTOM"], ["项目代号-朱雀", "孤立敏感词"])
        self.assertEqual(words["CN_MOBILE"], ["13800138000"])

    def test_load_words_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "words.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("姓名:张三\n")
            self.assertEqual(load_words_file(path), {"PERSON": ["张三"]})


class PolicyBuildTests(unittest.TestCase):
    def test_empty_enabled_is_not_replaced_by_defaults(self) -> None:
        policy = build_policy(enabled=[])
        self.assertEqual(policy.enabled, set())
        self.assertNotEqual(policy.enabled, set(DEFAULT_ENABLED))

    def test_disabled_is_applied(self) -> None:
        policy = build_policy(disabled=["EMAIL", "URL"])
        self.assertNotIn("EMAIL", policy.enabled)
        self.assertNotIn("URL", policy.enabled)

    def test_rules_disabled_overrides_enabled(self) -> None:
        policy = build_policy(rules={"enabled": ["EMAIL", "URL"], "disabled": ["URL"]})
        self.assertEqual(policy.enabled, {"EMAIL"})
        with self.assertRaises(ValueError):
            build_policy(rules={"enabled": "EMAIL"})
        with self.assertRaises(ValueError):
            build_policy(rules={"disabled": "URL"})

    def test_rules_file_and_custom_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(sample_rules(), fh, ensure_ascii=False)
            rules = load_rules_file(path)
            policy = build_policy(rules=rules)
            self.assertEqual(policy.strategy, "mask")
            self.assertEqual(policy.custom_words["PERSON"], ["张三", "李四"])
            self.assertEqual(len(policy.custom_patterns), 1)
            self.assertIn("PERSON", policy.enabled)
            self.assertNotIn("URL", policy.enabled)

    def test_invalid_rules_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{bad json")
            with self.assertRaises(ValueError):
                load_rules_file(path)
            with self.assertRaises(FileNotFoundError):
                load_rules_file(os.path.join(tmp, "missing.json"))


if __name__ == "__main__":
    unittest.main()
