"""E2E smoke test: drive the real server.py through one full user journey.

Stdlib only. Starts the real server as a subprocess on a free port with a
temp YAGNI_DATA dir, walks the journey over HTTP, restarts the server to
prove persistence, and asserts no Set-Cookie ever appeared.

Run: python smoke.py   ->  prints "SMOKE PASS", exit 0; nonzero on failure.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIE_VIOLATIONS = []


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(port: int, data_dir: str) -> subprocess.Popen:
    env = dict(os.environ, YAGNI_PORT=str(port), YAGNI_DATA=data_dir)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(f"server did not start on port {port}")


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    proc.wait(timeout=5)


def req(port: int, path: str, data=None):
    """One raw HTTP round trip; redirects are NOT followed. (status, headers, body)"""
    url = f"http://127.0.0.1:{port}{path}"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method="POST" if data is not None else "GET")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        resp = urllib.request.build_opener(NoRedirect).open(r, timeout=5)
        return record(port, resp.status, resp.headers, resp.read().decode())
    except urllib.error.HTTPError as e:
        return record(port, e.code, e.headers, e.read().decode())


def record(port, status, headers, body):
    """Every response in the run passes through here: catch cookie leaks."""
    if "Set-Cookie" in {k.title(): v for k, v in headers.items()}:
        COOKIE_VIOLATIONS.append(f"http://127.0.0.1:{port}")
    return status, headers, body


class SmokeError(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise SmokeError(msg)


def step(name, fn):
    try:
        fn()
        print(f"ok: {name}")
    except SmokeError as e:
        print(f"FAIL: {name}: {e}")
        raise


def main() -> int:
    port, data_dir = free_port(), tempfile.mkdtemp(prefix="yagni-smoke-")
    state = {}
    try:
        state["proc"] = start_server(port, data_dir)
        get = lambda p: req(port, p)
        post = lambda p, d: req(port, p, d)

        def journey_create_list():
            status, _, body = get("/")
            check(status == 200 and "YAGNI" in body, f"landing page: status={status}")
            status, headers, _ = post("/new", {"x": "1"})
            check(status in (302, 303), f"create list: status={status}")
            state["tok"] = headers["Location"][len("/l/"):]
            check(len(state["tok"]) >= 20, "token must be >= 20 chars")

        def journey_add_items():
            tok = state["tok"]
            status, _, _ = post(f"/l/{tok}/add",
                                {"name": "ThinkPad X1", "price": "1500", "url": "https://example.com/x1"})
            check(status in (200, 302, 303), f"add item 1: status={status}")
            status, _, _ = post(f"/l/{tok}/add", {"name": "Fancy Widget"})
            check(status in (200, 302, 303), f"add item 2: status={status}")

        def journey_verify_items():
            _, _, page = get(f"/l/{state['tok']}")
            check("ThinkPad X1" in page, "item 1 missing from page")
            check("1500" in page, "item 1 price missing from page")
            check("https://example.com/x1" in page, "item 1 link missing from page")
            check("Fancy Widget" in page, "item 2 missing from page")
            check("100 days left" in page, "days remaining missing from page")

        def journey_decide():
            tok = state["tok"]
            status, _, _ = post(f"/l/{tok}/item/1/decide", {"status": "bought"})
            check(status in (200, 302, 303), f"decide bought: status={status}")
            status, _, _ = post(f"/l/{tok}/item/2/decide", {"status": "dropped"})
            check(status in (200, 302, 303), f"decide dropped: status={status}")
            _, _, page = get(f"/l/{tok}")
            check("bought — decided" in page, "item 1 not marked bought")
            check("dropped — decided" in page, "item 2 not marked dropped")
            check("days left to decide" not in page, "undecided state still shown")

        def journey_delete():
            tok = state["tok"]
            status, _, _ = post(f"/l/{tok}/item/1/delete", {"x": "1"})
            check(status in (200, 302, 303), f"delete: status={status}")
            _, _, page = get(f"/l/{tok}")
            check("ThinkPad X1" not in page, "item 1 still on page after delete")
            check("dropped — decided" in page, "item 2 lost after deleting item 1")

        def journey_restart_persistence():
            stop_server(state.pop("proc"))
            state["proc"] = start_server(port, data_dir)
            _, _, page = get(f"/l/{state['tok']}")
            check("Fancy Widget" in page, "item 2 did not survive restart")
            check("dropped — decided" in page, "decided state did not survive restart")
            check("ThinkPad X1" not in page, "deleted item came back after restart")

        for name, fn in [
            ("landing page + create list", journey_create_list),
            ("add two items", journey_add_items),
            ("both items on page, 100 days left", journey_verify_items),
            ("decide bought + dropped", journey_decide),
            ("delete one item", journey_delete),
            ("restart server, state persists", journey_restart_persistence),
        ]:
            step(name, fn)

        check(not COOKIE_VIOLATIONS, f"Set-Cookie seen on: {COOKIE_VIOLATIONS}")
        print("ok: no Set-Cookie header anywhere")
        print("SMOKE PASS")
        return 0
    except SmokeError:
        print("SMOKE FAIL")
        return 1
    except Exception as e:
        print(f"SMOKE FAIL: {e}")
        return 1
    finally:
        if "proc" in state:
            stop_server(state["proc"])
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
