#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

backend_url="${FORECAST_BACKEND_URL:-http://localhost:8080}"
timeout_seconds="${FORECAST_STACK_TIMEOUT_SECONDS:-180}"
reset_and_import="${FORECAST_RESET_AND_IMPORT:-0}"
forecast_args=()

usage() {
  printf 'Usage: %s [--reset-and-import] [run-all-forecasts options]\n' "$0"
  printf 'Starts Docker background services, waits for the backend, then runs all forecasts.\n'
  printf 'Pass forecast options such as --target, --train-start, --train-days, --forecast-start, and --forecast-days.\n'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --reset-and-import)
      reset_and_import="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      forecast_args+=("$1")
      shift
      ;;
  esac
done

wait_for_backend() {
  local started_at
  started_at="$(date +%s)"
  until python3 - "$backend_url" <<'PY'
import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
params = urlencode({"target": "generation", "from": "2025-06-11T00:00:00Z", "to": "2025-06-12T00:00:00Z"})
try:
    with urlopen(f"{base_url}/api/forecast-datasets?{params}", timeout=5) as response:
        payload = json.load(response)
    if "points" not in payload:
        raise RuntimeError("response does not contain points")
except Exception as exc:
    print(f"Backend not ready: {exc}")
    sys.exit(1)
PY
  do
    if [ $(( $(date +%s) - started_at )) -ge "$timeout_seconds" ]; then
      printf '[forecast-setup] timed out waiting for backend at %s after %s seconds\n' "$backend_url" "$timeout_seconds" >&2
      docker compose --profile server ps >&2 || true
      docker compose --profile server logs --tail=80 backend >&2 || true
      exit 1
    fi
    sleep 2
  done
}

check_dataset_has_points() {
  python3 - "$backend_url" <<'PY'
import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
missing = []
for target in ("generation", "consumption"):
    params = urlencode({"target": target, "from": "2025-06-11T00:00:00Z", "to": "2025-06-12T00:00:00Z"})
    with urlopen(f"{base_url}/api/forecast-datasets?{params}", timeout=10) as response:
        payload = json.load(response)
    if not payload.get("points"):
        missing.append(target)
if missing:
    raise SystemExit("No imported forecast dataset points found for: " + ", ".join(missing))
PY
}

printf '[forecast-setup] start Docker background services\n'
./run-server.sh

if [ "$reset_and_import" = "1" ]; then
  printf '[forecast-setup] reset and import CSV data\n'
  ./reset-and-import-data.sh
  printf '[forecast-setup] restart backend after import\n'
  ./run-server.sh
fi

printf '[forecast-setup] wait for backend at %s\n' "$backend_url"
wait_for_backend

printf '[forecast-setup] check imported dataset points\n'
check_dataset_has_points

printf '[forecast-setup] backend and data checks passed\n'
printf '[forecast-setup] run forecast batch\n'
./run-all-forecasts.sh "${forecast_args[@]}"
