from __future__ import annotations

import unittest

from docmask.validators import cn_id_valid, ipv4_valid, luhn_valid, uscc_valid
from tests.helpers import make_cn_id, make_uscc


class LuhnTests(unittest.TestCase):
    def test_valid_card(self) -> None:
        self.assertTrue(luhn_valid("4111111111111111"))
        self.assertTrue(luhn_valid("5555555555554444"))

    def test_invalid_card(self) -> None:
        self.assertFalse(luhn_valid("4111111111111112"))
        self.assertFalse(luhn_valid("4111-1111-1111-1111"))
        self.assertFalse(luhn_valid(""))


class CnIdTests(unittest.TestCase):
    def test_valid_generated_id(self) -> None:
        value = make_cn_id()
        self.assertEqual(len(value), 18)
        self.assertTrue(cn_id_valid(value))
        self.assertTrue(cn_id_valid(value.lower()))

    def test_invalid_ids(self) -> None:
        valid = make_cn_id()
        wrong_check = valid[:17] + ("0" if valid[17] != "0" else "1")
        self.assertFalse(cn_id_valid(wrong_check))
        mutated_body = valid[:6] + ("0" if valid[6] != "0" else "1") + valid[7:]
        self.assertFalse(cn_id_valid(mutated_body))
        self.assertFalse(cn_id_valid("110105194913310021"))
        self.assertFalse(cn_id_valid("11010519491231002"))


class UsccTests(unittest.TestCase):
    def test_valid_generated_code(self) -> None:
        value = make_uscc()
        self.assertTrue(uscc_valid(value))
        self.assertTrue(uscc_valid(value.lower()))

    def test_invalid_code(self) -> None:
        valid = make_uscc()
        wrong_check = valid[:17] + ("0" if valid[17] != "0" else "1")
        self.assertFalse(uscc_valid(wrong_check))
        self.assertFalse(uscc_valid("91330100MA2ABCDE"))
        self.assertFalse(uscc_valid("I" * 18))


class IpTests(unittest.TestCase):
    def test_ipv4(self) -> None:
        self.assertTrue(ipv4_valid("192.168.1.1"))
        self.assertTrue(ipv4_valid("0.0.0.0"))
        self.assertFalse(ipv4_valid("256.1.1.1"))
        self.assertFalse(ipv4_valid("192.168.01.1"))
        self.assertFalse(ipv4_valid("1.2.3"))
        self.assertFalse(ipv4_valid(""))


if __name__ == "__main__":
    unittest.main()
