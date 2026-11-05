from __future__ import annotations

import os
import threading
import unittest
import urllib.request

from docmask.desktop import _icon_path, run_app
from docmask.web.server import (
    _STATIC_DIR,
    _policy_from_options,
    _safe_filename,
    start_server,
)


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


class DesktopTests(unittest.TestCase):
    def test_icon_is_bundled(self) -> None:
        icon = _icon_path()
        self.assertIsNotNone(icon)
        self.assertTrue(os.path.isfile(icon))

    def test_run_app_is_callable(self) -> None:
        self.assertTrue(callable(run_app))

    def test_start_server_serves_healthz(self) -> None:
        httpd, _url, _root = start_server(port=0, announce=False)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            port = httpd.server_address[1]
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
