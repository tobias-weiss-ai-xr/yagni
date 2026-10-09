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
:root{color-scheme:dark}
*{box-sizing:border-box;margin:0}
body{background:#0d1117;color:#e6edf3;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;max-width:40rem;margin:0 auto;padding:2.5rem 1.25rem 3rem}
a{color:#58a6ff}
h1{color:#58a6ff;font-size:clamp(2.4rem,9vw,3.6rem);letter-spacing:.04em;line-height:1;margin-top:1.5rem}
h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.14em;color:#8b949e;margin:2.4rem 0 .8rem}
.tagline{font-size:1.15rem;margin-top:1rem}
.lede{color:#8b949e;margin-top:.5rem}
.steps,.checks{list-style:none;padding:0}
.steps{counter-reset:step}
.steps li{counter-increment:step;background:#161b22;border:1px solid #21262d;border-left:3px solid #58a6ff;border-radius:8px;padding:.75rem 1rem;margin:.6rem 0}
.steps li::before{content:counter(step);display:inline-block;width:1.4rem;height:1.4rem;line-height:1.4rem;text-align:center;border-radius:50%;background:#58a6ff;color:#0d1117;font-weight:700;margin-right:.55rem;font-size:.85rem}
.checks li{color:#8b949e;margin:.35rem 0}
.checks li::before{content:"✓";color:#3fb950;font-weight:700;margin-right:.5rem}
input,button{font:inherit;border-radius:8px}
input{background:#0d1117;color:#e6edf3;border:1px solid #30363d;padding:.5rem .75rem}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:.5rem 1.1rem;cursor:pointer}
button:hover{border-color:#58a6ff;color:#58a6ff}
.primary{background:#238636;border-color:#238636;color:#fff;font-weight:600;padding:.6rem 1.2rem}
.primary:hover{background:#2ea043;color:#fff}
.meta{color:#8b949e;white-space:nowrap}
.badge{display:inline-block;padding:.15rem .45rem;background:#21262d;border:1px solid #30363d;border-radius:4px;font-size:.85rem;color:#8b949e;white-space:nowrap}
.warn{background:#f0883e1a;color:#f0883e;border-color:#f0883e!important}
.actions{display:flex;gap:.4rem;margin-top:.4rem;flex-wrap:wrap}
.actions form{margin:0}
.actions button{background:#21262d;border:1px solid #484f58;color:#8b949e;padding:.35rem .7rem;font-size:.85rem}
.actions button:hover{background:#30363d;color:#e6edf3;border-color:#58a6ff}
input:focus,button:focus-visible,a:focus-visible{outline:2px solid #58a6ff;outline-offset:2px}
.item{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:.9rem 1.1rem;margin:.8rem 0}
.muted{color:#8b949e}.dropped{color:#3fb950}.bought{color:#f0883e}
footer{margin-top:3rem;padding-top:1.2rem;border-top:1px solid #21262d;font-size:.8rem;color:#484f58}
footer a{color:#6e7681}
"""

SITE = "https://yagni.graphwiz.ai"
DESC = ("Park a purchase desire for 100 days, then decide: still want it, buy it; "
        "urge dead, drop it. Free impulse control with no accounts, no cookies, "
        "no tracking, no JavaScript.")

LLMS = f"""# YAGNI

YAGNI ({SITE}/) is a free, privacy-first impulse-control web app implementing the
classic 100-day purchase rule: you park a desired purchase on a private list,
wait exactly 100 days, then decide. Still want it? Buy it, guilt-free. The urge
died? Drop it, and you kept the money. Impulse control as a service.

## How it works

1. Create a list without signing up. The secret /l/<token> URL is the only
   credential - bookmark it.
2. Add items (name, price, link). Each item gets an immutable decide date
   exactly 100 days after creation.
3. When the countdown ends, mark the item bought or dropped. Decisions keep no
   history.

## Facts

- Free of charge, no account required. An optional magic-code email login
  recovers lost list URLs (6-digit code, no passwords).
- Privacy: no cookies, no analytics, no JavaScript, no request logs, no
  third-party requests.
- State is one JSON file written atomically; the server is a single Python 3
  stdlib file, MIT licensed.
- Source code: https://github.com/tobias-weiss-ai-xr/yagni
"""

ROBOTS = "User-agent: *\nAllow: /\nDisallow: /l/\n"


def esc(s):
    return html.escape(str(s), quote=True)


def page(title, body, extra_head="", indexable=False):
    robots = "" if indexable else '<meta name="robots" content="noindex">'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{robots}<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#9203;</text></svg>">
<title>{esc(title)} — YAGNI</title>
{extra_head}
<style>{STYLE}</style></head><body>
{body}
<footer><a href="/">yagni.graphwiz.ai</a> · <a href="https://github.com/tobias-weiss-ai-xr/yagni">source</a> · MIT · no cookies, no logs, no JS</footer>
</body></html>"""


SEO_HEAD = f"""<meta name="description" content="{DESC}">
<link rel="canonical" href="{SITE}/">
<meta property="og:type" content="website">
<meta property="og:title" content="YAGNI — the 100-day impulse rule">
<meta property="og:description" content="{DESC}">
<meta property="og:url" content="{SITE}/">
<meta name="theme-color" content="#0d1117">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebApplication","name":"YAGNI","url":"{SITE}/","applicationCategory":"LifestyleApplication","operatingSystem":"Web","description":"{DESC}","offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}}}}</script>"""


LANDING = page("The 100-day impulse rule", f"""
<h1>YAGNI</h1>
<p class="tagline">Park a purchase desire for 100 days. Still want it then?
<b>Buy it</b> — guilt-free. The urge died? <b>Drop it</b> — money kept.</p>
<p class="lede">Impulse control as a service. No account needed: your secret
list URL is the auth, and it's unguessable.</p>
<h2>How it works</h2>
<ol class="steps">
<li><b>Add the thing.</b> Name, price, link — the 100-day deadline is set
automatically and can't be changed.</li>
<li><b>Wait it out.</b> Bookmark your secret list URL and let the countdown
run.</li>
<li><b>Decide.</b> Mark it <span class="bought">bought</span> or
<span class="dropped">dropped</span>. No history, no judgment.</li>
</ol>
<form method="post" action="/new"><button class="primary">Create a list — free</button></form>
<h2>Privacy is the product</h2>
<ul class="checks">
<li>No accounts, no passwords — the secret URL is the auth</li>
<li>No cookies, no analytics, no third-party requests, no JavaScript</li>
<li>No request logs — no IPs, no user agents, nothing persisted</li>
<li>One JSON file on a trusted host is the entire state</li>
</ul>
<h2>Lost your list URL?</h2>
<p class="muted">Link an email to your list and we'll send a 6-digit code to
get you back in. No passwords, ever.</p>
<form method="post" action="/login"><input name="email" type="email" placeholder="email" required><button>Send code</button></form>
""", extra_head=SEO_HEAD, indexable=True)

LOGIN_PAGE = page("Log in", """
<h1>YAGNI</h1>
<p class="tagline">Welcome back.</p>
<p class="lede">Enter your email and the 6-digit code we sent you.</p>
<form method="post" action="/login/verify">
<input name="email" type="email" placeholder="email" required>
<input name="code" inputmode="numeric" pattern="[0-9]{6}" placeholder="6-digit code" required>
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
        if it["status"]:
            state_html = f'<span class="badge {it["status"]}">{it["status"]} — decided</span>'
        else:
            days = days_left(it["decide_at"], now)
            cls = "warn" if days <= 7 else ""
            state_html = f'<span class="badge {cls}">{days} days left</span>'
        price = f'<span class="meta">{esc(it["price"])}</span>' if it["price"] else ""
        link = f'<a class="meta" href="{esc(it["url"])}">link</a>' if it["url"] else ""
        meta = " ".join(filter(None, [price, link]))
        base = f"/l/{tok}/item/{it['id']}"
        rows.append(f"""<div class="item">
<b>{esc(it["name"])}</b>{meta}
{state_html}
<div class="actions">
<form method="post" action="{base}/decide"><input type="hidden" name="status" value="bought"><button>buy</button></form>
<form method="post" action="{base}/decide"><input type="hidden" name="status" value="dropped"><button>drop</button></form>
<form method="post" action="{base}/delete"><button>delete</button></form>
</div>
</div>""")
    items = "".join(rows) or '<p class="muted">Nothing parked yet. Add the thing you want to want.</p>'
    email = f'<p class="muted">email linked: {esc(lst["email"])}</p>' if lst.get("email") else ""
    return page("Your list", f"""
<h1>Your list</h1>
{email}
<p class="lede">Add the thing you want to want. The 100-day clock starts the
moment you add it.</p>
<form method="post" action="/l/{tok}/add">
<input name="name" placeholder="What do you want?" required>
<input name="price" placeholder="price (optional)">
<input name="url" placeholder="url (optional)">
<button class="primary">Add</button></form>
{items}
<h2>Recovery email</h2>
<p class="muted">Lost this URL? Link an email and sign back in with a 6-digit
code.</p>
<form method="post" action="/l/{tok}/link"><input name="email" type="email" placeholder="email" required><button>Send code</button></form>
<form method="post" action="/l/{tok}/verify"><input name="code" inputmode="numeric" pattern="[0-9]{{6}}" placeholder="6-digit code"><button>Verify</button></form>
""")


def render_lists_page():
    email = LOGIN_STATE["email"]
    if not email:
        return page("Your lists", '<h1>Your lists</h1><p class="muted">No active login. Log in from the start page first.</p>')
    rows = "".join(f'<p><a href="/l/{t}">/l/{t}</a></p>' for t, l in STORE.items() if l.get("email") == email)
    empty = '<p class="muted">No lists linked yet.</p>'  # py3.8: no backslash in f-string expr
    return page("Your lists", f"<h1>Lists for {esc(email)}</h1>{rows or empty}")


# --- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # privacy: no request logs, ever
        pass

    def send_html(self, body, code=200, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
        elif path == "/llms.txt":
            self.send_html(LLMS, ctype="text/plain; charset=utf-8")
        elif path == "/robots.txt":
            self.send_html(ROBOTS, ctype="text/plain; charset=utf-8")
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
