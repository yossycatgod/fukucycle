#!/bin/zsh
set -e
cd "${0:A:h}"

if ! command -v cloudflared >/dev/null 2>&1; then
  print "cloudflared が必要です: brew install cloudflared"
  exit 1
fi

FUKUCYCLE_PORT="${FUKUCYCLE_PORT:-8080}"
FUKUCYCLE_PORT="$FUKUCYCLE_PORT" python3 serve.py &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM
sleep 3
cloudflared tunnel --url "http://127.0.0.1:$FUKUCYCLE_PORT"
