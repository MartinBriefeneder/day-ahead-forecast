#!/usr/bin/env bash
set -euo pipefail

script_dir="$(dirname "$0")"

cd "$script_dir/python"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

python3 main.py
python3 barebones_openstef.py --target generation
python3 tuned_openstef.py --target generation
python3 custom_openstef.py --target generation
python3 compare_forecasts.py
