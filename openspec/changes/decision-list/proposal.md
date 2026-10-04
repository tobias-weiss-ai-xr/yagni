## Why

The joke page becomes the product: yagni.graphwiz.ai should host the actual YAGNI tool — a personal list where you park a purchase desire for 100 days before deciding. After 100 days you either still want it (buy) or the urge died (drop). Impulse control as a service.

## What Changes

- Server-side decision-list app (replaces the static joke page as the main artifact)
- No accounts: each list is a secret URL (128-bit token) — knowing the URL is the auth
- Items: name, optional price/URL, created date, automatic 100-day decision deadline, buy/drop decision
- Privacy-first server: Python 3 stdlib only, no cookies, no request logging, no IPs stored, localhost-default bind

## Capabilities

### New Capabilities

- `decision-list`: token-private lists, add/decide/delete flow, 100-day deadline, privacy guarantees

### Modified Capabilities

- (none)

## Impact

- New `server.py` (stdlib-only HTTP server) + `smoke.py` E2E + privacy docs in README
- `data/` directory holds list state at runtime (gitignored)
- Workers/build: orchestrated via agentflow (`af run`) — contract tests land first, implementation tasks are gated on them
