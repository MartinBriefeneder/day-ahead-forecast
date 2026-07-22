#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/python"
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
