#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
source .venv/bin/activate

export SQAO_API_URL="${SQAO_API_URL:-https://sqao-live-api.onrender.com}"
export DERIV_SYMBOL="${DERIV_SYMBOL:-AUTO}"
export SQAO_HISTORY_CANDLES="${SQAO_HISTORY_CANDLES:-500}"

mkdir -p DATA
python -m CONNECTOR.deriv_live > DATA/connector.log 2>&1 &
CONNECTOR_PID=$!
echo "$CONNECTOR_PID" > DATA/connector.pid

cleanup() {
  if kill -0 "$CONNECTOR_PID" 2>/dev/null; then kill "$CONNECTOR_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

streamlit run AI/app.py --server.address 0.0.0.0 --server.port "${PORT:-8501}"
