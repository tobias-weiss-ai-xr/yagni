## Why

The secret URL is the only key — lose it and the list is gone, and items hit their 100-day deadline silently. Email login (magic-code, no passwords) adds recovery and lets the app send decision-due notices. Privacy posture is preserved: email is the only identity, codes are ephemeral, no passwords, no tracking.

## What Changes

- **Email link**: a list owner can attach an email to a list (6-digit code sent by mail, verified once)
- **Login**: returning users request a code by email and see all lists linked to that address (recovery)
- **Notify**: items reaching their 100-day deadline trigger one decision-due mail (idempotent via notified flag); run via `notify.py` + systemd timer
- **SMTP via env**: `YAGNI_SMTP_MODE=none|file|smtp` (file mode for tests, smtplib for production via local mailcow relay)
- **Test pyramid upgraded to three gated layers**: unit (`test_unit.py`, pure functions) → contract (`test_app.py`, HTTP) → E2E (`smoke.py`, full journey) — each layer is an af acceptance gate

## Capabilities

### New Capabilities

- `email-auth`: link email to list, code verification, login by email, anti-enumeration behavior

### Modified Capabilities

- (none — notify rides on `decision-list` deadlines; no requirement changes there)

## Impact

- `server.py` gains auth routes + pure helpers (importable, `main()` guarded); new `notify.py`; SMTP env config
- Store schema: optional `email` + ephemeral `codes` per list (back-compat with existing `data/lists.json`)
- Deploy: SMTP relay env (mailcow on host) + systemd timer for daily notify
