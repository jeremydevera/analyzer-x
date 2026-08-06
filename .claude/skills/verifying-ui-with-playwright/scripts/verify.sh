#!/usr/bin/env bash
# Bootstrap Playwright next to this script on first run, then verify the page.
#   ./verify.sh <url> [tabName] [--find "text"]... [--wait ms] [--dump-testids]
set -euo pipefail
cd "$(dirname "$0")"
if ! node -e "import('playwright')" 2>/dev/null; then
  echo "bootstrapping playwright…" >&2
  npm init -y >/dev/null 2>&1
  npm i playwright --no-audit --no-fund >/dev/null
  npx playwright install chromium-headless-shell >/dev/null 2>&1 || npx playwright install chromium >/dev/null
fi
node verify.mjs "$@"
