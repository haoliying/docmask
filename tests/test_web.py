from __future__ import annotations

import unittest

from docmask.web.server import _policy_from_options, _safe_filename, _STATIC_DIR


class WebPolicyTests(unittest.TestCase):
    def test_options_build_policy(self) -> None:
        policy = _policy_from_options(
            {
                "enabled": ["email", "cn_mobile"],
                "strategy": "partial",
                "mask_char": "#",
                "keep_length": True,
                "strip_metadata": False,
                "custom_words": {"PERSON": ["张三", "x"]},
                "rules_text": '{"custom_patterns": [{"type": "EMP", "pattern": "EMP-\\\\d{6}"}]}',
            }
        )
        self.assertEqual(policy.enabled, {"EMAIL", "CN_MOBILE"})
        self.assertEqual(policy.strategy, "partial")
        self.assertEqual(policy.mask_char, "#")
        self.assertTrue(policy.keep_length)
        self.assertFalse(policy.strip_metadata)
        self.assertEqual(policy.custom_words["PERSON"], ["张三"])
        self.assertEqual(len(policy.custom_patterns), 1)

    def test_invalid_options(self) -> None:
        with self.assertRaises(ValueError):
            _policy_from_options({"enabled": "EMAIL"})
        with self.assertRaises(ValueError):
            _policy_from_options({"strategy": "unknown"})
        with self.assertRaises(ValueError):
            _policy_from_options({"rules_text": "not json"})
        with self.assertRaises(ValueError):
            _policy_from_options({"mask_char": "<"})


class FilenameTests(unittest.TestCase):
    def test_traversal_is_stripped(self) -> None:
        self.assertEqual(_safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(_safe_filename("C:\\temp\\报告.docx"), "报告.docx")

    def test_empty_name(self) -> None:
        self.assertEqual(_safe_filename(""), "upload")
        self.assertEqual(_safe_filename(".."), "upload")

    def test_name_length_is_capped(self) -> None:
        name = _safe_filename("a" * 300 + ".txt")
        self.assertLessEqual(len(name), 125)


class StaticAssetTests(unittest.TestCase):
    def test_static_files_exist(self) -> None:
        for name in ("index.html", "app.css", "app.js"):
            path = _STATIC_DIR / name
            self.assertTrue(path.is_file(), f"缺少静态资源 {name}")
            self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
