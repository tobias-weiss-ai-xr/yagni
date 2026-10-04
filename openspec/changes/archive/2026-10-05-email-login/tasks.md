## 1. Contracts (human-written, before implementation)

- [x] 1.1 Spec delta (email-auth)
- [x] 1.2 `test_unit.py` — pure-function layer (gate for AUTH)
- [x] 1.3 `test_app.py` extended: link/login/none-mode (gate for AUTH)
- [x] 1.4 `test_notify.py` — due-mail contract (gate for NOTIFY)

## 2. Implementation (af tasks)

- [x] 2.1 AUTH — server.py: pure helpers exposed, main() guarded, link/login routes, SMTP env modes
- [x] 2.2 NOTIFY — notify.py: due mailer, idempotent, reuses server helpers
- [x] 2.3 SMOKE2 — smoke.py: full email journey E2E

## 3. Ship

- [x] 3.1 All three layers green; af merges; ansible deploy updated (SMTP env + notify timer); live check
