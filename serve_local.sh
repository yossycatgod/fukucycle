#!/bin/zsh
set -e
cd "${0:A:h}"
FUKUCYCLE_PORT="${FUKUCYCLE_PORT:-8080}" python3 serve.py
