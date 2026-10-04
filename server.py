"""YAGNI decision-list server — Python 3 stdlib only, privacy-first.

Park a purchase desire for 100 days, then decide: buy it or drop it.
No accounts: the secret URL is the auth. No cookies, no request logs,
bound to 127.0.0.1, state in one JSON file written atomically.
"""
import html
import json
import math
import os
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("YAGNI_PORT", "8000"))
DATA_DIR = os.environ.get("YAGNI_DATA", "data")
STORE_PATH = os.path.join(DATA_DIR, "lists.json")
DECIDE_AFTER = 100 * 86400  # the 100-day rule, in seconds

STORE = {}  # token -> {"items": [item, ...]}

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
""")


def render_list(tok, lst):
    now = int(time.time())
    rows = []
    for it in lst["items"]:
        if it["status"]:
            state = f'<span class="{it["status"]}">{it["status"]} — decided</span>'
        else:
            days = max(0, math.ceil((it["decide_at"] - now) / 86400))
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
    return page("Your list", f"""
<h1>YAGNI</h1>
<form method="post" action="/l/{tok}/add">
<input name="name" placeholder="What do you want?" required>
<input name="price" placeholder="price (optional)">
<input name="url" placeholder="url (optional)">
<button>Add</button></form>
{items}""")


def save():
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STORE, f)
    os.replace(tmp, STORE_PATH)  # atomic: readers never see a half-written file


def load():
    if os.path.exists(STORE_PATH):
        with open(STORE_PATH, encoding="utf-8") as f:
            STORE.update(json.load(f))


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
            tok = secrets.token_urlsafe(16)
            STORE[tok] = {"items": []}
            save()
            self.redirect(f"/l/{tok}")
            return

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
                "decide_at": now + DECIDE_AFTER,
                "status": None,
            })
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
