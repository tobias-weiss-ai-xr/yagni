"""Unit layer of the yagni test pyramid.

Pure helpers from server.py — no HTTP, no SMTP, no files except load/save
roundtrip. These names are the contract: server.py MUST expose them.
Run: python test_unit.py
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402  (must be importable without starting the HTTP server)

DAY = 86400


class TestTokensAndCodes(unittest.TestCase):
    def test_make_token_unique_and_long(self):
        tokens = {server.make_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)
        for t in tokens:
            self.assertGreaterEqual(len(t), 20)

    def test_make_code_is_six_digits(self):
        for _ in range(50):
            c = server.make_code()
            self.assertEqual(len(c), 6)
            self.assertTrue(c.isdigit())


class TestEmailValidation(unittest.TestCase):
    def test_valid_addresses(self):
        for good in ("a@b.de", "user.name+tag@example.com", "x@sub.domain.org"):
            self.assertTrue(server.valid_email(good), good)

    def test_invalid_addresses(self):
        for bad in ("", "nope", "a@b", "a b@c.de", "@x.de", "a@", "a@b.c."):
            self.assertFalse(server.valid_email(bad), bad)


class TestDeadlines(unittest.TestCase):
    def test_deadline_is_exactly_100_days(self):
        self.assertEqual(server.deadline_for(1000), 1000 + 100 * DAY)

    def test_days_left(self):
        now = 10_000_000
        self.assertEqual(server.days_left(now + 5 * DAY, now), 5)
        self.assertEqual(server.days_left(now + 1, now), 0)  # due today, not negative


class TestCodes(unittest.TestCase):
    def test_correct_code_passes(self):
        now = time.time()
        ok, reason = server.check_code("123456", now + 60, 0, "123456", now)
        self.assertTrue(ok)

    def test_wrong_code_fails(self):
        now = time.time()
        ok, _ = server.check_code("123456", now + 60, 0, "654321", now)
        self.assertFalse(ok)

    def test_expired_code_fails(self):
        now = time.time()
        ok, _ = server.check_code("123456", now - 1, 0, "123456", now)
        self.assertFalse(ok)

    def test_too_many_attempts_locks(self):
        now = time.time()
        ok, _ = server.check_code("123456", now + 60, 5, "123456", now)
        self.assertFalse(ok)  # 5 failures -> locked even with the right code


class TestStoreRoundtrip(unittest.TestCase):
    def test_save_is_atomic_and_loads_back(self):
        tmp = tempfile.mkdtemp(prefix="yagni-unit-")
        path = os.path.join(tmp, "lists.json")
        store = {"tok1": {"items": [{"name": "x"}]}, "tok2": {"items": []}}
        server.save_store(path, store)
        self.assertEqual(server.load_store(path), store)
        leftovers = [f for f in os.listdir(tmp) if f != "lists.json"]
        self.assertEqual(leftovers, [], "atomic save must not leave temp files")

    def test_load_missing_returns_empty(self):
        self.assertEqual(
            server.load_store(os.path.join(tempfile.mkdtemp(), "nope.json")), {}
        )

    def test_load_old_store_without_email_keys(self):
        tmp = tempfile.mkdtemp(prefix="yagni-unit-")
        path = os.path.join(tmp, "lists.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"tok": {"items": [{"name": "old"}]}}')  # pre-email schema
        store = server.load_store(path)
        self.assertEqual(store["tok"]["items"][0]["name"], "old")


if __name__ == "__main__":
    unittest.main(verbosity=2)
