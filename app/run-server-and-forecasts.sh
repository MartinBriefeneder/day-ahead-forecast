#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

backend_url="${FORECAST_BACKEND_URL:-http://localhost:8080}"
timeout_seconds="${FORECAST_STACK_TIMEOUT_SECONDS:-180}"
data_timeout_seconds="${FORECAST_DATA_TIMEOUT_SECONDS:-120}"
reset_and_import="${FORECAST_RESET_AND_IMPORT:-0}"
forecast_args=()
target="all"
train_start=""
train_days="90"
forecast_start=""
forecast_days="7"

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
    --target)
      target="$2"
      forecast_args+=("$1" "$2")
      shift 2
      ;;
    --train-start)
      train_start="$2"
      forecast_args+=("$1" "$2")
      shift 2
      ;;
    --train-days)
      train_days="$2"
      forecast_args+=("$1" "$2")
      shift 2
      ;;
    --forecast-start)
      forecast_start="$2"
      forecast_args+=("$1" "$2")
      shift 2
      ;;
    --forecast-days)
      forecast_days="$2"
      forecast_args+=("$1" "$2")
      shift 2
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

resolve_default_forecast_start() {
  python3 - <<'PY'
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
minute = (now.minute // 15 + 1) * 15
value = now.replace(minute=0) + timedelta(hours=1) if minute == 60 else now.replace(minute=minute)
print(value.isoformat().replace("+00:00", "Z"))
PY
}

preflight_forecast_data() {
  python3 - "$backend_url" "$target" "$train_start" "$train_days" "$forecast_start" "$forecast_days" "$data_timeout_seconds" <<'PY'
from datetime import datetime, timedelta, timezone
import json
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
target_arg = sys.argv[2]
train_start_arg = sys.argv[3]
train_days = int(sys.argv[4])
forecast_start = datetime.fromisoformat(sys.argv[5].replace("Z", "+00:00")).astimezone(timezone.utc)
forecast_days = int(sys.argv[6])
data_timeout_seconds = int(sys.argv[7])
targets = ("generation", "consumption") if target_arg == "all" else (target_arg,)
now = datetime.now(timezone.utc)

def format_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def parse_utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def fetch_points(target, start, end):
    params = urlencode({"target": target, "from": format_utc(start), "to": format_utc(end)})
    url = f"{base_url}/api/forecast-datasets?{params}"
    last_exception = None
    for attempt in range(1, 4):
        try:
            with urlopen(url, timeout=data_timeout_seconds) as response:
                payload = json.load(response)
            break
        except Exception as exc:
            last_exception = exc
            print(f"[forecast-setup] data query retry {attempt}/3 target={target} error={exc}", flush=True)
            time.sleep(2)
    else:
        raise RuntimeError(f"Data query failed for {target} {format_utc(start)} to {format_utc(end)}: {last_exception}")
    points = payload.get("points", [])
    timestamps = [point.get("timestamp") for point in points if point.get("timestamp")]
    return points, min(timestamps) if timestamps else None, max(timestamps) if timestamps else None

def expected_intervals(start, end):
    return int((end - start).total_seconds() // (15 * 60))

if train_start_arg:
    openstef_train_start = parse_utc(train_start_arg)
elif forecast_start >= now:
    openstef_train_start = parse_utc("2025-06-11T00:00:00Z")
else:
    openstef_train_start = forecast_start - timedelta(days=train_days)
openstef_train_end = openstef_train_start + timedelta(days=train_days)
if forecast_start < now:
    openstef_train_end = forecast_start

if train_start_arg:
    weekly_train_start = parse_utc(train_start_arg)
elif forecast_start >= now:
    weekly_train_start = parse_utc("2025-06-01T00:00:00Z")
else:
    weekly_train_start = forecast_start - timedelta(days=train_days)
weekly_query_end = min(weekly_train_start + timedelta(days=train_days), forecast_start) if forecast_start >= now else forecast_start + timedelta(days=forecast_days)

failures = []
for target in targets:
    for label, start, end in (
        ("weekly-persistence training", weekly_train_start, weekly_query_end),
        ("openstef training", openstef_train_start, openstef_train_end),
    ):
        points, first_timestamp, last_timestamp = fetch_points(target, start, end)
        expected = expected_intervals(start, end)
        print(
            f"[forecast-setup] data {target} {label}: "
            f"rows={len(points)}/{expected} start={format_utc(start)} end={format_utc(end)} "
            f"first={first_timestamp} last={last_timestamp}",
            flush=True,
        )
        if len(points) < expected:
            failures.append(f"{target} {label} has {len(points)} rows, expected {expected}")

if failures:
    raise SystemExit("Imported data preflight failed: " + "; ".join(failures))
PY
}

case "$target" in
  generation|consumption|all)
    ;;
  *)
    printf '[forecast-setup] invalid target: %s\n' "$target" >&2
    exit 2
    ;;
esac

if [ -z "$forecast_start" ]; then
  forecast_start="$(resolve_default_forecast_start)"
  forecast_args+=(--forecast-start "$forecast_start")
fi

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

printf '[forecast-setup] preflight imported forecast data\n'
preflight_forecast_data

printf '[forecast-setup] backend and data checks passed\n'
printf '[forecast-setup] run forecast batch\n'
./run-all-forecasts.sh "${forecast_args[@]}"
