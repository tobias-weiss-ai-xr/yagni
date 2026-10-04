"""Contract tests for the yagni decision-list server.

These are the acceptance gate for the `server` task: server.py passes when
this file passes. Stdlib only. Run: python test_app.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    def __init__(self):
        self.port = free_port()
        self.data = tempfile.mkdtemp(prefix="yagni-test-")
        self.mail = os.path.join(self.data, "smtp-out.txt")
        env = dict(
            os.environ,
            YAGNI_PORT=str(self.port),
            YAGNI_DATA=self.data,
            YAGNI_SMTP_MODE="file",
            YAGNI_SMTP_FILE=self.mail,
        )
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{self.port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")

    def stop(self, keep_data=False):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        if not keep_data:
            shutil.rmtree(self.data, ignore_errors=True)

    def req(self, path, data=None):
        """Returns (status, headers, body). Follows redirects manually."""
        url = f"http://127.0.0.1:{self.port}{path}"
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
        r = urllib.request.Request(url, data=body, method="POST" if data is not None else "GET")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(r, timeout=5)
            return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()


    def load_store(self):
        path = os.path.join(self.data, "lists.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def read_mail(self):
        if not os.path.exists(self.mail):
            return ""
        with open(self.mail, encoding="utf-8") as f:
            return f.read()


def code_from_mail(mail_text, after):
    """Last 6-digit code appearing after byte offset `after`."""
    import re

    codes = re.findall(r"\b(\d{6})\b", mail_text[after:])
    return codes[-1] if codes else None


class TestContract(unittest.TestCase):
    def setUp(self):
        self.srv = Server()
        self.addCleanup(self.srv.stop)

    def test_01_landing_page(self):
        status, _, body = self.srv.req("/")
        self.assertEqual(status, 200)
        self.assertIn("YAGNI", body)
        self.assertIn("/new", body)  # create-list form

    def test_02_create_list_redirects_to_token_url(self):
        status, headers, _ = self.srv.req("/", data={"x": "1"})
        self.assertIn(status, (302, 303))
        loc = headers.get("Location", "")
        self.assertTrue(loc.startswith("/l/"), loc)
        token = loc[len("/l/"):]
        self.assertGreaterEqual(len(token), 20, "token must be >= 20 chars")

    def test_03_unknown_token_is_404(self):
        status, _, _ = self.srv.req("/l/" + "x" * 40)
        self.assertEqual(status, 404)

    def test_04_add_item_deadline_is_100_days(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        status, _, _ = self.srv.req(
            f"/l/{tok}/add",
            data={"name": "ThinkPad X1", "price": "1500", "url": "https://example.com/x1"},
        )
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertIn("ThinkPad X1", page)
        self.assertIn("100", page)  # days remaining shown
        # Stored deadline is exactly created + 100 days.
        store = json.load(open(os.path.join(self.srv.data, "lists.json"), encoding="utf-8"))
        item = store[tok]["items"][0]
        self.assertEqual(item["decide_at"] - item["created_at"], 100 * 86400)

    def test_05_decide_and_delete(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        self.srv.req(f"/l/{tok}/add", data={"name": "Fancy Widget"})
        status, _, _ = self.srv.req(f"/l/{tok}/item/1/decide", data={"status": "dropped"})
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertIn("dropped", page.lower())
        status, _, _ = self.srv.req(f"/l/{tok}/item/1/delete", data={"x": "1"})
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertNotIn("Fancy Widget", page)

    def test_06_privacy_no_cookies(self):
        self.srv.req("/")
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        _, _, page = self.srv.req(f"/l/{tok}")
        self.srv.req(f"/l/{tok}/add", data={"name": "x"})
        for h in (headers,):
            self.assertNotIn("Set-Cookie", {k.title(): v for k, v in h.items()})

    def test_07_state_survives_restart(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        self.srv.req(f"/l/{tok}/add", data={"name": "Restart Survivor"})
        data_dir = self.srv.data
        self.srv.stop(keep_data=True)  # wipe only the process, keep the state
        env = dict(os.environ, YAGNI_PORT=str(self.srv.port), YAGNI_DATA=data_dir)
        self.srv.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.srv.proc.terminate)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.srv.port}/", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertIn("Restart Survivor", page)

    def test_08_link_email_with_code(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        self.srv.req(f"/l/{tok}/add", data={"name": "Linked Thing"})
        mark = len(self.srv.read_mail())
        status, _, _ = self.srv.req(
            f"/l/{tok}/link", data={"email": "owner@example.com"}
        )
        self.assertIn(status, (200, 302, 303))
        mail = self.srv.read_mail()
        self.assertIn("owner@example.com", mail)
        code = code_from_mail(mail, mark)
        self.assertIsNotNone(code)
        status, _, page = self.srv.req(f"/l/{tok}/verify", data={"code": code})
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertIn("owner@example.com", page)
        store = self.srv.load_store()
        self.assertEqual(store[tok].get("email"), "owner@example.com")

    def test_09_wrong_code_rejected_and_locks(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        mark = len(self.srv.read_mail())
        self.srv.req(f"/l/{tok}/link", data={"email": "lock@example.com"})
        code = code_from_mail(self.srv.read_mail(), mark)
        for _ in range(5):
            self.srv.req(f"/l/{tok}/verify", data={"code": "000000"})
        status, _, page = self.srv.req(f"/l/{tok}/verify", data={"code": code})
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req(f"/l/{tok}")
        self.assertNotIn("lock@example.com", page)  # locked: even right code fails

    def test_10_login_returns_linked_lists(self):
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        mark = len(self.srv.read_mail())
        self.srv.req(f"/l/{tok}/link", data={"email": "login@example.com"})
        code = code_from_mail(self.srv.read_mail(), mark)
        self.srv.req(f"/l/{tok}/verify", data={"code": code})
        mark = len(self.srv.read_mail())
        status, _, _ = self.srv.req("/login", data={"email": "login@example.com"})
        self.assertIn(status, (200, 302, 303))
        code2 = code_from_mail(self.srv.read_mail(), mark)
        self.assertIsNotNone(code2)
        status, _, page = self.srv.req(
            "/login/verify", data={"email": "login@example.com", "code": code2}
        )
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req("/lists")
        self.assertIn(f"/l/{tok}", page)

    def test_11_login_unknown_email_no_enumeration(self):
        status, _, page = self.srv.req("/login", data={"email": "ghost@example.com"})
        self.assertIn(status, (200, 302, 303))  # same shape as known emails
        status, _, page = self.srv.req(
            "/login/verify", data={"email": "ghost@example.com", "code": "111111"}
        )
        self.assertIn(status, (200, 302, 303))
        _, _, page = self.srv.req("/lists")
        self.assertNotIn("/l/", page)  # no list URLs leaked

    def test_12_smtp_none_mode_fails_cleanly(self):
        self.srv.stop()
        env = dict(
            os.environ,
            YAGNI_PORT=str(self.srv.port),
            YAGNI_DATA=self.srv.data,
            YAGNI_SMTP_MODE="none",
        )
        self.srv.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.srv.proc.terminate)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.srv.port}/", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        _, headers, _ = self.srv.req("/", data={"x": "1"})
        tok = headers["Location"][len("/l/"):]
        status, _, _ = self.srv.req(
            f"/l/{tok}/link", data={"email": "x@example.com"}
        )
        self.assertGreaterEqual(status, 400)  # clean error, no crash, no fake success

    def test_13_server_module_importable(self):
        # test_unit.py imports server.py; main() must be guarded.
        with open(os.path.join(ROOT, "server.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('if __name__ == "__main__"', src)
        self.assertIn("def main(", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
