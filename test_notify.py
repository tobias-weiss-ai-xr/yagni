"""Contract for notify.py — decision-due mailer.

Runs the real script as a subprocess (no imports), against a crafted store.
Run: python test_notify.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
DAY = 86400
NOW = 1_800_000_000  # fixed "now" for determinism


def write_store(data_dir, store):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "lists.json"), "w", encoding="utf-8") as f:
        json.dump(store, f)


def run_notify(data_dir, mail_file):
    return subprocess.run(
        [
            sys.executable,
            os.path.join(ROOT, "notify.py"),
            "--data", data_dir,
            "--smtp-file", mail_file,
            "--now", str(NOW),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def read(mail_file):
    if not os.path.exists(mail_file):
        return ""
    with open(mail_file, encoding="utf-8") as f:
        return f.read()


class TestNotify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yagni-notify-")
        self.data = os.path.join(self.tmp, "data")
        self.mail = os.path.join(self.tmp, "smtp-out.txt")
        self.store = {
            "due": {
                "email": "due@example.com",
                "items": [
                    {"name": "Due Thing", "created_at": NOW - 101 * DAY,
                     "decide_at": NOW - 1 * DAY, "status": "waiting"}
                ],
            },
            "future": {
                "email": "future@example.com",
                "items": [
                    {"name": "Future Thing", "created_at": NOW - 10 * DAY,
                     "decide_at": NOW + 90 * DAY, "status": "waiting"}
                ],
            },
            "noemail": {
                "items": [
                    {"name": "Silent Thing", "created_at": NOW - 101 * DAY,
                     "decide_at": NOW - 1 * DAY, "status": "waiting"}
                ],
            },
        }
        write_store(self.data, self.store)

    def read_store(self):
        with open(os.path.join(self.data, "lists.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_01_due_item_gets_exactly_one_mail(self):
        r = run_notify(self.data, self.mail)
        self.assertEqual(r.returncode, 0, r.stderr)
        mail = read(self.mail)
        self.assertIn("due@example.com", mail)
        self.assertIn("Due Thing", mail)
        self.assertNotIn("Future Thing", mail)
        self.assertNotIn("Silent Thing", mail)  # list without email: skipped
        # item marked notified in the store
        item = self.read_store()["due"]["items"][0]
        self.assertTrue(item.get("notified"))

    def test_02_rerun_is_idempotent(self):
        run_notify(self.data, self.mail)
        size_after_first = os.path.getsize(self.mail)
        r = run_notify(self.data, self.mail)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.path.getsize(self.mail), size_after_first)

    def test_03_store_without_email_key_still_loads(self):
        # due list with legacy schema (no email key) must not crash notify
        self.store["legacy"] = {
            "items": [{"name": "Legacy Thing", "created_at": NOW - 101 * DAY,
                       "decide_at": NOW - 1 * DAY, "status": "waiting"}]
        }
        write_store(self.data, self.store)
        r = run_notify(self.data, self.mail)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Legacy Thing", read(self.mail))


if __name__ == "__main__":
    unittest.main(verbosity=2)
