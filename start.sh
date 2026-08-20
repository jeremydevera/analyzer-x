#!/bin/bash
# Start the app: React UI on 8503, Python API behind it on 8787.
#
# The UI proxies /api/* to the API (webapp/next.config.ts), so the operator
# only ever opens ONE url:  http://localhost:8503
#
# Ports are freed by PID, never by process name — `pkill -f streamlit` once
# killed the operator's own server.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
UI_PORT="${UI_PORT:-8503}"
API_PORT="${API_PORT:-8787}"
LOGS="$ROOT/.run"; mkdir -p "$LOGS"

free_port() {
  local pid; pid=$(lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null)
  [ -n "$pid" ] && { echo "freeing port $1 (pid $pid)"; kill $pid; sleep 1; }
}

case "${1:-start}" in
  stop)
    free_port "$UI_PORT"; free_port "$API_PORT"; echo "stopped"; exit 0 ;;
  status)
    for p in "$API_PORT" "$UI_PORT"; do
      pid=$(lsof -nP -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null)
      echo "port $p: ${pid:-free}"
    done
    curl -sf "http://localhost:$UI_PORT/api/health" >/dev/null \
      && echo "health: ok (UI is proxying the API)" || echo "health: NOT answering"
    exit 0 ;;
esac

free_port "$API_PORT"
free_port "$UI_PORT"

echo "starting API on $API_PORT…"
cd "$ROOT"
nohup "$ROOT/.venv/bin/uvicorn" tradingagents.api:app --host 127.0.0.1 \
  --port "$API_PORT" > "$LOGS/api.log" 2>&1 &
echo $! > "$LOGS/api.pid"

echo "building the UI…"
cd "$ROOT/webapp"
if ! npm run build > "$LOGS/build.log" 2>&1; then
  echo "BUILD FAILED — see $LOGS/build.log"; tail -20 "$LOGS/build.log"; exit 1
fi

echo "starting UI on $UI_PORT…"
API_ORIGIN="http://127.0.0.1:$API_PORT" nohup npx next start -p "$UI_PORT" \
  > "$LOGS/ui.log" 2>&1 &
echo $! > "$LOGS/ui.pid"

for i in $(seq 1 30); do
  sleep 1
  if curl -sf "http://localhost:$UI_PORT/api/health" >/dev/null; then
    echo; echo "  ready:  http://localhost:$UI_PORT"; echo
    exit 0
  fi
done
echo "the UI did not answer in 30s — see $LOGS/ui.log"; tail -20 "$LOGS/ui.log"; exit 1
