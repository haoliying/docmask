from __future__ import annotations

import os
import stat
import tempfile
import unittest

from docmask.masking import (
    Masker,
    Redactor,
    Restorer,
    apply_replacements,
    load_mapping,
)
from docmask.models import Match, Policy, Replacement
from tests.helpers import make_policy


def phone(value: str = "13800138000") -> Match:
    return Match(
        start=0,
        end=len(value),
        etype="CN_MOBILE",
        value=value,
        confidence=0.96,
        priority=80,
        detector="mobile_regex",
    )


class RenderTests(unittest.TestCase):
    def test_mask_default(self) -> None:
        masker = Masker(make_policy(strategy="mask"))
        self.assertEqual(masker.render(phone()), "***")

    def test_mask_keep_length(self) -> None:
        masker = Masker(make_policy(strategy="mask", keep_length=True))
        self.assertEqual(masker.render(phone()), "*" * 11)

    def test_partial_mobile(self) -> None:
        masker = Masker(make_policy(strategy="partial"))
        self.assertEqual(masker.render(phone()), "138****8000")

    def test_partial_email(self) -> None:
        match = Match(0, 17, "EMAIL", "alice@example.com")
        masker = Masker(make_policy(strategy="partial"))
        self.assertEqual(masker.render(match), "a***@example.com")

    def test_replace_is_stable_and_increments(self) -> None:
        masker = Masker(make_policy(strategy="replace"))
        first = masker.render(phone())
        second = masker.render(phone())
        other = masker.render(phone("13900139000"))
        self.assertEqual(first, "[MOBILE_001]")
        self.assertEqual(second, first)
        self.assertEqual(other, "[MOBILE_002]")
        self.assertEqual(masker.counts["CN_MOBILE"], 3)

    def test_hash_is_deterministic_for_same_salt(self) -> None:
        first = Masker(make_policy(strategy="hash", salt="s1")).render(phone())
        second = Masker(make_policy(strategy="hash", salt="s1")).render(phone())
        other = Masker(make_policy(strategy="hash", salt="s2")).render(phone())
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertRegex(first, r"^\[H_[0-9a-f]{10}\]$")

    def test_invalid_strategy(self) -> None:
        policy = Policy(strategy="unknown")
        with self.assertRaises(ValueError):
            policy.validate()

    def test_invalid_mask_char(self) -> None:
        with self.assertRaises(ValueError):
            Policy(mask_char="<").validate()
        with self.assertRaises(ValueError):
            Policy(mask_char="").validate()


class ApplyTests(unittest.TestCase):
    def test_apply_replacements(self) -> None:
        text = "电话 13800138000，邮箱 a@b.com"
        changes = [
            Replacement(3, 14, "***"),
            Replacement(18, 25, "[EMAIL]"),
        ]
        self.assertEqual(apply_replacements(text, changes), "电话 ***，邮箱 [EMAIL]")

    def test_overlapping_replacements_are_ignored(self) -> None:
        text = "abcdef"
        changes = [Replacement(1, 4, "X"), Replacement(2, 5, "Y")]
        self.assertEqual(apply_replacements(text, changes), "aXef")

    def test_redactor_transform(self) -> None:
        policy = make_policy(strategy="replace")
        redactor = Redactor(policy)
        changes = redactor.transform("手机 13800138000，邮箱 alice@example.com")
        self.assertEqual(len(changes), 2)
        self.assertEqual(
            apply_replacements("手机 13800138000，邮箱 alice@example.com", changes),
            "手机 [MOBILE_001]，邮箱 [EMAIL_001]",
        )


class MappingTests(unittest.TestCase):
    def test_write_load_restore(self) -> None:
        policy = make_policy(strategy="replace")
        masker = Masker(policy)
        masker.render(phone())
        masker.render(Match(0, 17, "EMAIL", "alice@example.com"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mapping.csv")
            masker.write_mapping(path)
            self.assertTrue(os.path.exists(path))
            if os.name == "posix":
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(mode, 0o600)
            mapping = load_mapping(path)
            self.assertEqual(mapping["[MOBILE_001]"], "13800138000")
            restorer = Restorer(mapping)
            changes = restorer.transform("联系 [MOBILE_001] 或 [EMAIL_001]")
            self.assertEqual(len(changes), 2)
            self.assertEqual(restorer.count, 2)
            self.assertEqual(
                apply_replacements("联系 [MOBILE_001] 或 [EMAIL_001]", changes),
                "联系 13800138000 或 alice@example.com",
            )

    def test_preview_render_does_not_leak(self) -> None:
        policy = make_policy(strategy="replace")
        redactor = Redactor(policy)
        text = "手机 13800138000"
        changes = redactor.transform(text)
        output = apply_replacements(text, changes)
        self.assertNotIn("13800138000", output)
        self.assertIn("[MOBILE_001]", output)


if __name__ == "__main__":
    unittest.main()
