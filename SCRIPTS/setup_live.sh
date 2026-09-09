#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ENGINE/requirements.txt
python -m ENGINE.tests
printf '\nSQAO LIVE ready. Start connector with: python -m CONNECTOR.deriv_live\n'
