"""Decision-due mailer — the 100-day rule needs a nag.

Finds waiting items whose decide_at has passed and mails the list owner,
once per item (idempotent via the "notified" flag). Reuses the server's
store and mail helpers. Run: python notify.py --data data --smtp-file smtp-out.txt
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402  (import is side-effect free; main() is guarded)


def is_due(it, now):
    """Waiting, not yet notified, and past its decide_at."""
    decide_at = it.get("decide_at")
    return (it.get("status") == "waiting" and not it.get("notified")
            and decide_at is not None and decide_at <= now)


def run(store, now):
    """Mail one nag per due item in lists that have an email. Returns mail count."""
    n = 0
    for tok, lst in store.items():
        email = lst.get("email")
        if not email:
            continue  # legacy/anonymous list: nothing to mail, leave untouched
        for it in lst.get("items", []):
            if not is_due(it, now):
                continue
            server.send_mail(
                email,
                f"YAGNI: time to decide about '{it['name']}'",
                f"'{it['name']}' hit its 100-day deadline ({server.days_left(it['decide_at'], now)} days left). "
                "Open your list and decide: buy it or drop it.")
            it["notified"] = True
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="YAGNI decision-due mailer")
    ap.add_argument("--data", default=server.DATA_DIR)
    ap.add_argument("--smtp-file", default=os.environ.get("YAGNI_SMTP_FILE", "smtp-out.txt"))
    ap.add_argument("--now", type=int, default=None, help="unix time override (tests)")
    args = ap.parse_args()

    store = server.load_store(os.path.join(args.data, "lists.json"))
    os.environ["YAGNI_SMTP_MODE"] = "file"
    os.environ["YAGNI_SMTP_FILE"] = args.smtp_file
    if run(store, args.now if args.now is not None else int(time.time())):
        server.save_store(os.path.join(args.data, "lists.json"), store)


if __name__ == "__main__":
    main()
