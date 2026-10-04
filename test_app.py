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
        env = dict(os.environ, YAGNI_PORT=str(self.port), YAGNI_DATA=self.data)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
