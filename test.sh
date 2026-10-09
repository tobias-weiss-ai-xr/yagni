#!/bin/sh
# Privacy contract, checked against the served landing page: no JS, no external
# fetches; JSON-LD is data, not code. Deeper layers:
#   python test_unit.py && python test_app.py && python smoke.py
set -e
cd "$(dirname "$0")"

test -f LICENSE && grep -q 'MIT License' LICENSE && echo "ok: MIT licensed"

YAGNI_PORT=8131 YAGNI_DATA="$(mktemp -d)" python server.py &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
PAGE=$(curl -sf http://127.0.0.1:8131/)

echo "$PAGE" | grep -qi '<h1>YAGNI</h1>' && echo "ok: headline"
echo "$PAGE" | grep -qi '<script type="application/ld+json">' && echo "ok: JSON-LD structured data"
NO_LD=$(echo "$PAGE" | sed 's/<script type="application\/ld+json">.*<\/script>//')
! echo "$NO_LD" | grep -qi '<script' && echo "ok: no javascript"
! echo "$PAGE" | grep -Eq 'src="https?://|href="https?://fonts|fetch\(' && echo "ok: zero external fetches"

echo "ALL PASS"
