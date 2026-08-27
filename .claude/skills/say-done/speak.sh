#!/bin/bash
# say-done speaker. Reads config.json AT SPEAK TIME so edits apply live to
# every session — no skill reloads. Edit config.json to change voice, rate,
# a suffix, or set enabled=false to silence it everywhere at once.
#
# Runs on the Mac (`say`) and on the Windows PC (SAPI through PowerShell).
# On 2026-08-27 every finished task on the Windows clone printed "Python was
# not found" instead of speaking: `python3` there is the Microsoft Store stub
# and `say` does not exist, so the config was never read and nothing was said.
DIR="$(cd "$(dirname "$0")" && pwd)"
MSG="$1"
[ -z "$MSG" ] && exit 0

# whichever python this machine really has — the Store stub prints its ad on
# stdout and exits 9009, so a --version check is what separates them
PY=""
for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" --version >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done
[ -z "$PY" ] && [ -x "$DIR/../../../.venv/Scripts/python.exe" ] \
    && PY="$DIR/../../../.venv/Scripts/python.exe"
[ -z "$PY" ] && [ -x "$DIR/../../../.venv/bin/python" ] \
    && PY="$DIR/../../../.venv/bin/python"

if [ -n "$PY" ]; then
    eval "$("$PY" - "$DIR/config.json" <<'PY'
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
else
    # no python at all is not a reason to go silent
    ENABLED=1; VOICE="Daniel"; FALLBACK="Daniel"; RATE=170; SUFFIX=""
fi
[ "$ENABLED" != "1" ] && exit 0

if command -v say >/dev/null 2>&1; then
    say -v '?' 2>/dev/null | grep -q "^${VOICE} " || VOICE="$FALLBACK"
    exec say -v "$VOICE" -r "$RATE" "${MSG}${SUFFIX}"
fi

# Windows: SAPI. `rate` is words-per-minute on the Mac and -10..10 here, so
# 145 wpm maps to roughly 0 and each 20 wpm is one step.
PWSH="$(command -v powershell.exe || command -v pwsh || true)"
if [ -n "$PWSH" ]; then
    TEXT="${MSG}${SUFFIX}"
    "$PWSH" -NoProfile -Command "
        Add-Type -AssemblyName System.Speech
        \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        \$s.Rate = [Math]::Max(-10, [Math]::Min(10, [int](($RATE - 145) / 20)))
        \$s.Speak([Console]::In.ReadToEnd())
    " <<< "$TEXT" >/dev/null 2>&1 &
    exit 0
fi
exit 0
