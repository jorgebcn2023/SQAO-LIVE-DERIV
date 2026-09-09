#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r ENGINE/requirements.txt

python -m compileall -q ENGINE CONNECTOR
python -m ENGINE.tests
python -m ENGINE.live_pipeline >/tmp/sqao-live-pipeline.json

printf '\nSQAO-LIVE-DERIV: OK\n'
printf '%s\n' 'Repositorio preparado para datos publicos de Deriv.'
printf '%s\n' 'No se requiere token para el canal de mercado publico.'
printf '%s\n' 'Iniciar: source .venv/bin/activate && python -m CONNECTOR.deriv_live'
printf '%s\n' 'Analisis vivo: DATA/live_analysis.json'
