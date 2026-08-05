#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -gt 0 ] && [[ "$1" != /* ]]; then
  artifact_dir="$app_dir/$1"
  shift
  set -- "$artifact_dir" "$@"
fi

cd "$app_dir/python"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
python3 forecast_from_model.py "$@"
