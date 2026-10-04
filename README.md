# yagni — the 100-day decision list

Park a purchase desire for **100 days**, then decide: still want it → buy it.
The urge died → drop it. Impulse control as a service, live at
[yagni.graphwiz.ai](https://yagni.graphwiz.ai/).

**No accounts — the secret URL is the auth.** Create a list, bookmark your
`/l/<token>` link, add items. Each item gets an automatic 100-day deadline.

## Run

```sh
python server.py            # binds 127.0.0.1:8000
```

- `YAGNI_PORT` — port (default 8000)
- `YAGNI_DATA` — data directory (default `data/`)

## Privacy-first

- No accounts, no email, no passwords — the secret URL **is** the auth
- **No cookies** — ever
- **No request logs** — no IPs, no user agents, nothing persisted
- No analytics, no third-party requests, no JavaScript
- State stays in one local JSON file (`data/lists.json`), written atomically
- Python 3 stdlib only — zero dependencies to audit

## The 100-day rule

Every item is created with an immutable `decide_at = created_at + 100 days`.
The list page shows the countdown. After 100 days, mark the item **bought**
(you still want it — buy without guilt) or **dropped** (the urge was
manufactured — you just saved the money). Decisions keep no history.

## Test

```sh
python test_app.py          # contract tests
python smoke.py             # full E2E user journey
```

## Deploy

Runs anywhere Python 3 runs. For non-localhost use, bind behind your own
reverse proxy (HTTPS terminates there) and keep `YAGNI_DATA` on a trusted
host — the JSON file is the only state there is.

MIT licensed. Built with [agentflow](https://github.com/tobias-weiss-ai-xr/agentflow)
— spec'd, contract-tested, and dispatched as `af` tasks.
