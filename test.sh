#!/bin/sh
# Smoke test: the whole product contract in four greps.
set -e
cd "$(dirname "$0")"

grep -qi '<h1>YAGNI</h1>' index.html && echo "ok: headline"
! grep -qi '<script' index.html && echo "ok: no javascript"
! grep -qE 'src="https?://|href="https?://fonts|fetch\(' index.html && echo "ok: zero external fetches"
test -f LICENSE && grep -q 'MIT License' LICENSE && echo "ok: MIT licensed"

echo "ALL PASS"
