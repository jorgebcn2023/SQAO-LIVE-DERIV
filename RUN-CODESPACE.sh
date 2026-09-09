#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r ENGINE/requirements.txt

python -m ENGINE.tests
python -m ENGINE.live_pipeline || true

echo
printf '%s\n' 'SQAO-LIVE-DERIV preparado.'
printf '%s\n' 'Para iniciar el conector en tiempo real:'
printf '%s\n' '  source .venv/bin/activate'
printf '%s\n' '  python -m CONNECTOR.deriv_live'
