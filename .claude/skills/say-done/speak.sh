#!/bin/bash
# say-done speaker. Reads config.json AT SPEAK TIME so edits apply live to
# every session — no skill reloads. Edit config.json to change voice, rate,
# a suffix, or set enabled=false to silence it everywhere at once.
DIR="$(cd "$(dirname "$0")" && pwd)"
MSG="$1"
[ -z "$MSG" ] && exit 0
eval "$(python3 - "$DIR/config.json" <<'PY'
import json, shlex, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    c = {}
print("ENABLED=" + ("1" if c.get("enabled", True) else "0"))
print("VOICE=" + shlex.quote(str(c.get("voice", "Daniel"))))
print("FALLBACK=" + shlex.quote(str(c.get("fallback_voice", "Daniel"))))
print("RATE=" + shlex.quote(str(c.get("rate", 170))))
print("SUFFIX=" + shlex.quote(str(c.get("suffix", ""))))
PY
)"
[ "$ENABLED" != "1" ] && exit 0
say -v '?' 2>/dev/null | grep -q "^${VOICE} " || VOICE="$FALLBACK"
exec say -v "$VOICE" -r "$RATE" "${MSG}${SUFFIX}"
