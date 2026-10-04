"""YAGNI decision-list server — Python 3 stdlib only, privacy-first.

Park a purchase desire for 100 days, then decide: buy it or drop it.
The secret URL is the auth; email (magic code, no passwords) adds
recovery. No cookies, no request logs, bound to 127.0.0.1, state in one
JSON file written atomically.
"""
import html
import json
import os
import re
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("YAGNI_PORT", "8000"))
DATA_DIR = os.environ.get("YAGNI_DATA", "data")
STORE_PATH = os.path.join(DATA_DIR, "lists.json")
DECIDE_AFTER = 100 * 86400  # the 100-day rule, in seconds
CODE_TTL = 15 * 60  # magic codes expire after 15 minutes
CODE_TRIES = 5  # failed attempts before a code is invalidated

STORE = {}  # token -> {"items": [...], "email": ..., "pending": {...}}
LOGIN_CODES = {}  # email -> {"code", "expires", "attempts"} — ephemeral, in-memory
LOGIN_STATE = {"email": None}  # ponytail: single pending login (127.0.0.1, single-user); per-client sessions if that ever changes

EMAIL_RE = re.compile(r"^[^@\s]+@([^.@\s]+\.)+[^.@\s]+$")


# --- pure helpers (unit-layer contract) -----------------------------------

def make_token():
    return secrets.token_urlsafe(16)


def make_code():
    return f"{secrets.randbelow(1000000):06d}"


def valid_email(s):
    return bool(EMAIL_RE.match(s))


def deadline_for(created_at):
    return created_at + DECIDE_AFTER


def days_left(decide_at, now):
    return max(0, (decide_at - now) // 86400)


def check_code(given, expires_at, attempts, expected, now):
    """One magic-code attempt -> (ok, reason)."""
    if attempts >= CODE_TRIES:
        return False, "locked"
    if now >= expires_at:
        return False, "expired"
    if not secrets.compare_digest(str(given), str(expected)):
        return False, "wrong"
    return True, "ok"


# --- store ----------------------------------------------------------------

def save_store(path, store):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f)
    os.replace(tmp, path)  # atomic: readers never see a half-written file


def load_store(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save():
    save_store(STORE_PATH, STORE)


def load():
    STORE.update(load_store(STORE_PATH))


# --- mail: one function, reused by server and notify.py -------------------

def send_mail(to, subject, body):
    """Send via YAGNI_SMTP_MODE: file | smtp. Raises RuntimeError when none."""
    mode = os.environ.get("YAGNI_SMTP_MODE", "none")
    sender = os.environ.get("YAGNI_SMTP_FROM", "yagni@localhost")
    msg = f"From: {sender}\nTo: {to}\nSubject: {subject}\n\n{body}\n"
    if mode == "file":
        path = os.environ.get("YAGNI_SMTP_FILE", "smtp-out.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg)
    elif mode == "smtp":
        import smtplib
        host = os.environ.get("YAGNI_SMTP_HOST", "localhost")
        port = int(os.environ.get("YAGNI_SMTP_PORT", "25"))
        with smtplib.SMTP(host, port) as s:
            s.sendmail(sender, [to], msg)
    else:
        raise RuntimeError("YAGNI_SMTP_MODE=none: mail sending is disabled")


# --- rendering ------------------------------------------------------------

STYLE = """
body{background:#111;color:#eee;font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
a{color:#8cf}form{display:inline}
input,button{background:#222;color:#eee;border:1px solid #444;padding:.4rem .6rem;border-radius:4px}
.item{border:1px solid #333;border-radius:6px;padding:.8rem;margin:.8rem 0}
.muted{color:#999}.dropped{color:#8f8}.bought{color:#fb4}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def page(title, body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — YAGNI</title>
<style>{STYLE}</style></head><body>
{body}
</body></html>"""


LANDING = page("YAGNI", """
<h1>YAGNI</h1>
<p>Park a purchase desire for 100 days. Still want it then? Buy it.
The urge died? Drop it. Impulse control as a service.</p>
<form method="post" action="/new"><button>Create a list</button></form>
<h2>Log in</h2>
<p>Lost your list URL? We send a 6-digit code to your email.</p>
<form method="post" action="/login"><input name="email" placeholder="email"><button>Send code</button></form>
""")

LOGIN_PAGE = page("Log in", """
<h1>YAGNI</h1>
<p>Enter the email and the 6-digit code we sent you.</p>
<form method="post" action="/login/verify">
<input name="email" placeholder="email">
<input name="code" placeholder="6-digit code">
<button>Verify</button></form>
""")


def render_list(tok, lst):
    now = int(time.time())
    rows = []
    for it in lst["items"]:
        if it["status"]:
            state = f'<span class="{it["status"]}">{it["status"]} — decided</span>'
        else:
            days = days_left(it["decide_at"], now)
            state = f'<span class="muted">{days} days left to decide</span>'
        price = f" — {esc(it['price'])}" if it["price"] else ""
        link = f' <a href="{esc(it["url"])}">link</a>' if it["url"] else ""
        base = f"/l/{tok}/item/{it['id']}"
        rows.append(f"""<div class="item"><b>{esc(it["name"])}</b>{price}{link}<br>{state}<br>
<form method="post" action="{base}/decide"><input type="hidden" name="status" value="bought"><button>buy</button></form>
<form method="post" action="{base}/decide"><input type="hidden" name="status" value="dropped"><button>drop</button></form>
<form method="post" action="{base}/delete"><button>delete</button></form>
</div>""")
    items = "".join(rows) or '<p class="muted">Empty. Add the thing you want to want.</p>'
    email = f'<p>email linked: {esc(lst["email"])}</p>' if lst.get("email") else ""
    return page("Your list", f"""
<h1>YAGNI</h1>
{email}
<form method="post" action="/l/{tok}/add">
<input name="name" placeholder="What do you want?" required>
<input name="price" placeholder="price (optional)">
<input name="url" placeholder="url (optional)">
<button>Add</button></form>
{items}
<h2>Recovery email</h2>
<form method="post" action="/l/{tok}/link"><input name="email" placeholder="email"><button>Send code</button></form>
<form method="post" action="/l/{tok}/verify"><input name="code" placeholder="6-digit code"><button>Verify</button></form>
""")


def render_lists_page():
    email = LOGIN_STATE["email"]
    if not email:
        return page("Your lists", '<h1>YAGNI</h1><p class="muted">No active login. Log in from the start page first.</p>')
    rows = "".join(f'<p><a href="/l/{t}">/l/{t}</a></p>' for t, l in STORE.items() if l.get("email") == email)
    empty = '<p class="muted">No lists linked yet.</p>'  # py3.8: no backslash in f-string expr
    return page("Your lists", f"<h1>Lists for {esc(email)}</h1>{rows or empty}")


# --- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # privacy: no request logs, ever
        pass

    def send_html(self, body, code=200):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def redirect(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form(self):
        n = int(self.headers.get("Content-Length", 0))
        return urllib.parse.parse_qs(self.rfile.read(n).decode())

    def not_found(self):
        self.send_error(404)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self.send_html(LANDING)
        elif path == "/login":
            self.send_html(LOGIN_PAGE)
        elif path == "/lists":
            self.send_html(render_lists_page())
        elif path.startswith("/l/"):
            tok = path[len("/l/"):]
            if tok in STORE:
                self.send_html(render_list(tok, STORE[tok]))
            else:
                self.not_found()
        else:
            self.not_found()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self.form()
        parts = path.strip("/").split("/")

        if path in ("/", "/new"):  # create list
            tok = make_token()
            STORE[tok] = {"items": []}
            save()
            self.redirect(f"/l/{tok}")
            return

        if path == "/login":  # request a login code
            email = form.get("email", [""])[0].strip()
            if valid_email(email) and any(l.get("email") == email for l in STORE.values()):
                code = make_code()
                LOGIN_CODES[email] = {"code": code, "expires": time.time() + CODE_TTL, "attempts": 0}
                send_mail(email, "Your YAGNI code", f"Your YAGNI code: {code}\nIt expires in 15 minutes.")
            self.redirect("/login")  # same shape for unknown addresses: no enumeration
            return

        if path == "/login/verify":
            email = form.get("email", [""])[0].strip()
            given = form.get("code", [""])[0].strip()
            pend = LOGIN_CODES.get(email)
            if pend is not None:
                ok, _ = check_code(given, pend["expires"], pend["attempts"], pend["code"], time.time())
                if ok:
                    LOGIN_STATE["email"] = email
                    del LOGIN_CODES[email]
                    return self.redirect("/lists")
                pend["attempts"] += 1
                if pend["attempts"] >= CODE_TRIES:
                    del LOGIN_CODES[email]
            return self.redirect("/login")

        if len(parts) == 3 and parts[0] == "l" and parts[2] == "add":  # add item
            tok = parts[1]
            if tok not in STORE:
                return self.not_found()
            name = form.get("name", [""])[0].strip()
            if not name:
                return self.redirect(f"/l/{tok}")
            items = STORE[tok]["items"]
            now = int(time.time())
            items.append({
                "id": max((i["id"] for i in items), default=0) + 1,
                "name": name,
                "price": form.get("price", [""])[0].strip(),
                "url": form.get("url", [""])[0].strip(),
                "created_at": now,
                "decide_at": deadline_for(now),
                "status": None,
            })
            save()
            self.redirect(f"/l/{tok}")
            return

        if len(parts) == 3 and parts[0] == "l" and parts[2] == "link":  # attach recovery email
            tok = parts[1]
            lst = STORE.get(tok)
            if lst is None:
                return self.not_found()
            email = form.get("email", [""])[0].strip()
            if not valid_email(email):
                return self.redirect(f"/l/{tok}")
            code = make_code()
            try:
                send_mail(email, "Your YAGNI code", f"Your YAGNI code: {code}\nIt expires in 15 minutes.")
            except RuntimeError:
                return self.send_error(503, "mail sending disabled (YAGNI_SMTP_MODE=none)")
            lst["pending"] = {"email": email, "code": code, "expires": time.time() + CODE_TTL, "attempts": 0}
            save()
            self.redirect(f"/l/{tok}")
            return

        if len(parts) == 3 and parts[0] == "l" and parts[2] == "verify":  # confirm magic code
            tok = parts[1]
            lst = STORE.get(tok)
            if lst is None:
                return self.not_found()
            given = form.get("code", [""])[0].strip()
            pend = lst.get("pending")
            if pend is not None:
                ok, _ = check_code(given, pend["expires"], pend["attempts"], pend["code"], time.time())
                if ok:
                    lst["email"] = pend["email"]
                    del lst["pending"]
                else:
                    pend["attempts"] += 1
                    if pend["attempts"] >= CODE_TRIES:
                        del lst["pending"]  # invalidated after 5 failures
                save()
            self.redirect(f"/l/{tok}")
            return

        if len(parts) == 5 and parts[0] == "l" and parts[4] in ("decide", "delete"):
            tok, action = parts[1], parts[4]
            lst = STORE.get(tok)
            if lst is None:
                return self.not_found()
            try:
                iid = int(parts[3])
            except ValueError:
                return self.not_found()
            it = next((i for i in lst["items"] if i["id"] == iid), None)
            if it is None:
                return self.not_found()
            if action == "decide":
                status = form.get("status", [""])[0]
                if status in ("bought", "dropped"):
                    it["status"] = status
                    save()
            else:
                lst["items"].remove(it)
                save()
            self.redirect(f"/l/{tok}")
            return

        self.not_found()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    load()
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
