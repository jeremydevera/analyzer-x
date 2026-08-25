#!/bin/bash
# Thin wrapper for macOS / Linux. The launcher itself is start.py — ONE
# implementation for every OS (Windows uses start.cmd). Until 2026-08-25 this
# file WAS the launcher (lsof, nohup, curl, .venv/bin/uvicorn) and the
# operator's Windows PC could not start the app at all.
#
#   ./start.sh            # React UI on 8503, Python API on 8787 behind it
#   ./start.sh status     # which ports are held, and whether the API answers
#   ./start.sh stop       # free both ports by PID, never by name
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$ROOT/start.py" "$@"
