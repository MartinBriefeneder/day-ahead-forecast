#!/usr/bin/env bash
set -euo pipefail

script_dir="$(dirname "$0")"

cd "$script_dir/python"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

for target in generation consumption; do
  python3 main.py --target "$target" --save
  python3 default_openstef_xgboost.py --target "$target"
  python3 tuned_openstef.py --target "$target"
  python3 custom_openstef.py --target "$target"
  python3 compare_forecasts.py --target "$target"
done
