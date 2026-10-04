"""E2E smoke test: drive the real server.py through one full user journey.

Stdlib only. Starts the real server as a subprocess on a free port with a
temp YAGNI_DATA dir (SMTP in file mode), walks the base journey plus the
full email journey (link, login recovery, due mail) over HTTP, restarts
the server to prove persistence, and asserts no Set-Cookie ever appeared.

Run: python smoke.py   ->  prints "SMOKE PASS", exit 0; nonzero on failure.
"""
import json
import os
import re
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


def start_server(port: int, data_dir: str, smtp_file: str) -> subprocess.Popen:
    env = dict(os.environ, YAGNI_PORT=str(port), YAGNI_DATA=data_dir,
               YAGNI_SMTP_MODE="file", YAGNI_SMTP_FILE=smtp_file)
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


def read_mails(path):
    """The smtp file as a list of RFC822-ish records, one per mail."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [m for m in re.split(r"(?m)^(?=From: )", f.read()) if m.strip()]


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
    smtp_file = os.path.join(data_dir, "smtp-out.txt")
    state = {}
    try:
        state["proc"] = start_server(port, data_dir, smtp_file)
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
            state["proc"] = start_server(port, data_dir, smtp_file)
            _, _, page = get(f"/l/{state['tok']}")
            check("Fancy Widget" in page, "item 2 did not survive restart")
            check("dropped — decided" in page, "decided state did not survive restart")
            check("ThinkPad X1" not in page, "deleted item came back after restart")

        def new_code(before):
            """The 6-digit code from the exactly-one mail that arrived since `before`."""
            mails = read_mails(smtp_file)
            check(len(mails) == before + 1, f"expected 1 new mail, got {len(mails) - before}")
            m = re.search(r"code: (\d{6})", mails[-1])
            check(m is not None, "mail contains no 6-digit code")
            return m.group(1)

        def journey_link_email():
            tok, email = state["tok"], "recovery@example.com"
            post(f"/l/{tok}/add", {"name": "Due Thing"})
            before = len(read_mails(smtp_file))
            status, _, _ = post(f"/l/{tok}/link", {"email": email})
            check(status in (200, 302, 303), f"link email: status={status}")
            status, _, _ = post(f"/l/{tok}/verify", {"code": new_code(before)})
            check(status in (200, 302, 303), f"verify email code: status={status}")
            _, _, page = get(f"/l/{tok}")
            check(f"email linked: {email}" in page, "linked email not shown on list page")
            state["email"] = email

        def journey_link_second_list():
            email = state["email"]
            status, headers, _ = post("/new", {"x": "1"})
            check(status in (302, 303), f"create list 2: status={status}")
            tok2 = headers["Location"][len("/l/"):]
            before = len(read_mails(smtp_file))
            status, _, _ = post(f"/l/{tok2}/link", {"email": email})
            check(status in (200, 302, 303), f"link list 2: status={status}")
            status, _, _ = post(f"/l/{tok2}/verify", {"code": new_code(before)})
            check(status in (200, 302, 303), f"verify list 2: status={status}")
            state["tok2"] = tok2

        def journey_login_recovery():
            email = state["email"]
            before = len(read_mails(smtp_file))
            status, _, _ = post("/login", {"email": email})
            check(status in (302, 303), f"login code request: status={status}")
            after_unknown_request = len(read_mails(smtp_file))
            status, _, _ = post("/login", {"email": "nobody@example.com"})
            check(status in (302, 303), f"unknown-address login shape: status={status}")
            check(len(read_mails(smtp_file)) == after_unknown_request,
                  "code mailed for unknown address (enumeration leak)")
            status, _, _ = post("/login/verify", {"email": email, "code": new_code(before)})
            check(status in (302, 303), f"login verify: status={status}")
            _, _, lists_page = get("/lists")
            check(f"/l/{state['tok']}" in lists_page, "recovered page missing list 1")
            check(f"/l/{state['tok2']}" in lists_page, "recovered page missing list 2")

        def journey_due_mail():
            stop_server(state.pop("proc"))
            store_path = os.path.join(data_dir, "lists.json")
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
            item = next(i for i in store[state["tok"]]["items"] if i["name"] == "Due Thing")
            now = int(time.time())
            item.update(created_at=now - 101 * 86400, decide_at=now - 86400, status="waiting")
            item.pop("notified", None)
            with open(store_path, "w", encoding="utf-8") as f:
                json.dump(store, f)
            before = len(read_mails(smtp_file))
            for _ in range(2):  # second run must not duplicate
                r = subprocess.run(
                    [sys.executable, os.path.join(ROOT, "notify.py"),
                     "--data", data_dir, "--smtp-file", smtp_file, "--now", str(now)],
                    capture_output=True, text=True, timeout=60)
                check(r.returncode == 0, f"notify.py failed: {r.stderr}")
            due = read_mails(smtp_file)[before:]
            check(len(due) == 1, f"expected exactly 1 due mail, got {len(due)}")
            check("recovery@example.com" in due[0], "due mail not addressed to the list email")
            check("Due Thing" in due[0], "due mail does not mention the item")
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
            item = next(i for i in store[state["tok"]]["items"] if i["name"] == "Due Thing")
            check(item.get("notified") is True, "notified flag not persisted")

        def journey_final_persistence():
            state["proc"] = start_server(port, data_dir, smtp_file)
            _, _, page1 = get(f"/l/{state['tok']}")
            check("Fancy Widget" in page1, "item did not survive restart")
            check("email linked: recovery@example.com" in page1, "list 1 email lost after restart")
            check("Due Thing" in page1, "due item lost after restart")
            _, _, page2 = get(f"/l/{state['tok2']}")
            check("email linked: recovery@example.com" in page2, "list 2 email lost after restart")

        for name, fn in [
            ("landing page + create list", journey_create_list),
            ("add two items", journey_add_items),
            ("both items on page, 100 days left", journey_verify_items),
            ("decide bought + dropped", journey_decide),
            ("delete one item", journey_delete),
            ("restart server, state persists", journey_restart_persistence),
            ("link email via magic code", journey_link_email),
            ("link a second list to the same email", journey_link_second_list),
            ("login by email recovers both lists", journey_login_recovery),
            ("due item gets exactly one mail", journey_due_mail),
            ("restart again: email + items persist", journey_final_persistence),
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
