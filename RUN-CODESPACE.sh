#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== SQAO LIVE DERIV :: Codespace bootstrap =="
echo "ROOT=$ROOT"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ENGINE/requirements.txt

echo
printf '%s\n' '== Python =='
python --version
printf '%s\n' '== Package smoke test =='
python -m ENGINE.tests

echo
printf '%s\n' '== Pipeline smoke test =='
set +e
python -m ENGINE.live_pipeline
PIPE_RC=$?
set -e

if [ "$PIPE_RC" -ne 0 ]; then
  echo "Pipeline exited with code $PIPE_RC. This can be expected before DATA/ is populated."
fi

echo
echo "SETUP_OK"
echo
echo "Next step:"
echo "  source .venv/bin/activate"
echo "  python -m CONNECTOR.deriv_live"
echo
echo "The connector uses public Deriv market data and does not require an API token."
