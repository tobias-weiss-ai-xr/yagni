## ADDED Requirements

### Requirement: Email link (magic code, no passwords)

A list owner SHALL be able to attach an email address to their list: submitting the address sends a 6-digit code to that address; entering the code within 15 minutes links the email to the list. Wrong codes are rejected; after 5 failed attempts the code is invalidated. No password is ever stored.

#### Scenario: Link and verify

- **WHEN** an owner submits `owner@example.com` on the list page and then enters the code from the mail
- **THEN** the list page shows the email as linked and the store records it

### Requirement: Login by email

The landing page SHALL offer login by email: submitting an address sends a code, entering it shows all list URLs linked to that address. For unknown addresses the response SHALL be identical in shape (no account enumeration); when SMTP is unconfigured (`YAGNI_SMTP_MODE=none`) the flows SHALL fail with a clear error and not crash.

#### Scenario: Recover lists

- **WHEN** a user logs in with the email linked to two lists
- **THEN** the page shows both list URLs

### Requirement: Decision-due notification

A `notify.py` run SHALL send exactly one mail per item whose `decide_at <= now`, addressed to the list email, and mark the item notified (re-runs SHALL not duplicate). Lists without an email are skipped.

#### Scenario: Due item gets one mail

- **WHEN** notify runs twice at the same `now` over a due item
- **THEN** exactly one mail is sent and the second run sends none

### Requirement: SMTP abstraction via environment

Outgoing mail SHALL go through `YAGNI_SMTP_MODE`: `file` (append RFC822 text to `YAGNI_SMTP_FILE`; used by tests), `smtp` (smittlib to `YAGNI_SMTP_HOST`/`YAGNI_SMTP_PORT`, sender `YAGNI_SMTP_FROM`), `none` (default). Mail sending SHALL live in one function reused by server and notify.

#### Scenario: File mode in tests

- **WHEN** the server runs with file mode and a code is requested
- **THEN** the mail text lands in the file and contains the code

### Requirement: Three-layer test pyramid as acceptance gates

The repo SHALL carry three test layers, all runnable with stdlib only: unit (`test_unit.py` — pure helpers, no HTTP), contract (`test_app.py` — HTTP behavior), E2E (`smoke.py` — full user journey). Implementation tasks are accepted per layer.

#### Scenario: Layers pass independently

- **WHEN** `python test_unit.py`, `python test_app.py`, `python smoke.py` run
- **THEN** all three pass

### Requirement: Backward-compatible store

Existing `data/lists.json` files without email/codes keys SHALL load unchanged; save SHALL remain atomic.

#### Scenario: Old store loads

- **WHEN** the server starts over a pre-email store
- **THEN** lists render and no keys are required
