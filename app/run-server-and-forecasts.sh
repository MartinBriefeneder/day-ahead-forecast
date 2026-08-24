#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:=$DEFAULT_INFLUXDB_TOKEN}"
: "${INFLUXDB_ORG:=kirchdorf}"
: "${INFLUXDB_BUCKET:=energy}"
export INFLUXDB_TOKEN INFLUXDB_ORG INFLUXDB_BUCKET

backend_url="${FORECAST_BACKEND_URL:-http://localhost:8080}"
timeout_seconds="${FORECAST_STACK_TIMEOUT_SECONDS:-180}"
data_timeout_seconds="${FORECAST_DATA_TIMEOUT_SECONDS:-120}"
data_chunk_hours="${FORECAST_DATA_CHUNK_HOURS:-24}"
runner_mode="${FORECAST_RUNNER_MODE:-docker}"
strict_data_preflight="${FORECAST_STRICT_DATA_PREFLIGHT:-0}"
min_training_days="${FORECAST_MIN_TRAINING_DAYS:-14}"
import_verify_timeout_seconds="${FORECAST_IMPORT_VERIFY_TIMEOUT_SECONDS:-300}"
reset_and_import="${FORECAST_RESET_AND_IMPORT:-0}"
auto_import="${FORECAST_AUTO_IMPORT:-1}"
csv_directory="${ENERGY_IMPORT_DIRECTORY:-./quarkus/data/csv_Archiv}"
default_train_start="${FORECAST_DEFAULT_TRAIN_START:-2025-06-11T00:00:00Z}"
forecast_args=()
target="all"
train_start=""
train_days="90"
forecast_start=""
forecast_days="7"
forecast_days_explicit="0"

usage() {
  printf 'Usage: %s [--reset-and-import] [run-all-forecasts options]\n' "$0"
  printf 'Starts the Docker server stack, imports CSV data when the database is empty, then runs all forecasts.\n'
  printf 'Pass forecast options such as --target, --train-start, --train-days, --forecast-start, and --forecast-days.\n'
  printf 'Use --csv-directory DIR to override the default CSV directory.\n'
  printf 'Plain runs also use FORECAST_DEFAULT_TRAIN_START when --train-start is omitted.\n'
  printf 'Set FORECAST_RUNNER_MODE=host to use the host Python virtual environment instead of Docker.\n'
  printf 'Set FORECAST_STRICT_DATA_PREFLIGHT=1 to fail on incomplete requested training windows.\n'
  printf 'Set FORECAST_AUTO_IMPORT=0 to fail instead of importing when no data exists.\n'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --reset-and-import)
      reset_and_import="1"
      shift
      ;;
    --csv-directory)
      csv_directory="$2"
      shift 2
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
      forecast_days_explicit="1"
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
  local consecutive_successes
  started_at="$(date +%s)"
  consecutive_successes=0
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
    consecutive_successes=0
    if [ $(( $(date +%s) - started_at )) -ge "$timeout_seconds" ]; then
      printf '[forecast-setup] timed out waiting for backend at %s after %s seconds\n' "$backend_url" "$timeout_seconds" >&2
      docker compose --profile server ps >&2 || true
      docker compose --profile server logs --tail=80 backend >&2 || true
      exit 1
    fi
    sleep 2
  done

  while [ "$consecutive_successes" -lt 2 ]; do
    if python3 - "$backend_url" <<'PY'
import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
params = urlencode({"target": "generation", "from": "2025-06-11T00:00:00Z", "to": "2025-06-11T00:15:00Z"})
try:
    with urlopen(f"{base_url}/api/forecast-datasets?{params}", timeout=5) as response:
        payload = json.load(response)
    if "points" not in payload:
        raise RuntimeError("response does not contain points")
except Exception as exc:
    print(f"Backend not stable yet: {exc}")
    sys.exit(1)
PY
    then
      consecutive_successes=$((consecutive_successes + 1))
    else
      consecutive_successes=0
    fi
    if [ $(( $(date +%s) - started_at )) -ge "$timeout_seconds" ]; then
      printf '[forecast-setup] timed out waiting for stable backend at %s after %s seconds\n' "$backend_url" "$timeout_seconds" >&2
      docker compose --profile server logs --tail=80 backend >&2 || true
      exit 1
    fi
    sleep 1
  done
}

start_server_stack() {
  mkdir -p ./reports/forecast-runs
  docker compose --profile server up -d --build --remove-orphans
  printf '[forecast-setup] backend: %s\n' "$backend_url"
  printf '[forecast-setup] grafana: http://localhost:3000\n'
  printf '[forecast-setup] influxdb: http://localhost:8086\n'
}

has_imported_data() {
  python3 - "$backend_url" "$data_timeout_seconds" <<'PY'
import json
import sys
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
timeout_seconds = int(sys.argv[2])
with urlopen(f"{base_url}/api/energy-import/status", timeout=timeout_seconds) as response:
    payload = json.load(response)
print("1" if payload.get("hasImportedData") else "0")
PY
}

run_backend_csv_import() {
  local import_dir

  if [ ! -d "$csv_directory" ]; then
    printf '[forecast-setup] CSV import directory does not exist: %s\n' "$csv_directory" >&2
    exit 1
  fi

  import_dir="$(realpath "$csv_directory")"
  printf '[forecast-setup] import CSV data through backend importer: %s\n' "$import_dir"
  docker compose --profile import run --rm \
    --volume "$import_dir:/import-data:ro" \
    importer
}

wait_for_any_imported_data() {
  local started_at
  local status

  started_at="$(date +%s)"
  while true; do
    if status="$(has_imported_data)" && [ "$status" = "1" ]; then
      return 0
    fi
    if [ $(( $(date +%s) - started_at )) -ge "$import_verify_timeout_seconds" ]; then
      return 1
    fi
    sleep 5
  done
}

ensure_imported_data_exists() {
  local status

  if ! status="$(has_imported_data)"; then
    printf '[forecast-setup] could not check imported data status through backend\n' >&2
    exit 1
  fi

  if [ "$status" = "1" ]; then
    printf '[forecast-setup] imported actual data found\n'
    return
  fi

  if [ "$auto_import" = "0" ]; then
    printf '[forecast-setup] no imported actual data found and FORECAST_AUTO_IMPORT=0\n' >&2
    exit 1
  fi

  printf '[forecast-setup] no imported actual data found; CSV import is required before forecasts\n'
  run_backend_csv_import

  if ! wait_for_any_imported_data; then
    printf '[forecast-setup] CSV import finished, but no imported actual data was found after %s seconds\n' "$import_verify_timeout_seconds" >&2
    exit 1
  fi
  printf '[forecast-setup] CSV import completed and imported actual data is available\n'
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
  python3 - "$backend_url" "$target" "$train_start" "$train_days" "$forecast_start" "$forecast_days" "$data_timeout_seconds" "$data_chunk_hours" "$strict_data_preflight" "$min_training_days" <<'PY'
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
data_chunk_hours = int(sys.argv[8])
strict_data_preflight = sys.argv[9] in {"1", "true", "TRUE", "yes", "YES"}
min_training_days = int(sys.argv[10])
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

def fetch_range_in_chunks(target, start, end):
    chunk_size = timedelta(hours=data_chunk_hours)
    if chunk_size.total_seconds() <= 0:
        raise RuntimeError("FORECAST_DATA_CHUNK_HOURS must be positive")
    all_points = []
    first_timestamp = None
    last_timestamp = None
    missing_chunks = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_size, end)
        points, chunk_first, chunk_last = fetch_points(target, chunk_start, chunk_end)
        expected = expected_intervals(chunk_start, chunk_end)
        all_points.extend(points)
        if chunk_first and (first_timestamp is None or chunk_first < first_timestamp):
            first_timestamp = chunk_first
        if chunk_last and (last_timestamp is None or chunk_last > last_timestamp):
            last_timestamp = chunk_last
        if len(points) < expected:
            missing_chunks.append(
                f"{format_utc(chunk_start)} to {format_utc(chunk_end)} rows={len(points)}/{expected}"
            )
        chunk_start = chunk_end
    return all_points, first_timestamp, last_timestamp, missing_chunks

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
total_points = 0
for target in targets:
    for label, start, end in (
        ("weekly-persistence training", weekly_train_start, weekly_query_end),
        ("openstef training", openstef_train_start, openstef_train_end),
    ):
        points, first_timestamp, last_timestamp, missing_chunks = fetch_range_in_chunks(target, start, end)
        expected = expected_intervals(start, end)
        total_points += len(points)
        print(
            f"[forecast-setup] data {target} {label}: "
            f"rows={len(points)}/{expected} start={format_utc(start)} end={format_utc(end)} "
            f"first={first_timestamp} last={last_timestamp}",
            flush=True,
        )
        if len(points) < expected:
            print(
                f"[forecast-setup] warning {target} {label}: incomplete requested window; forecasts will continue with available rows",
                flush=True,
            )
            for missing_chunk in missing_chunks[:10]:
                print(f"[forecast-setup] missing {target} {label}: {missing_chunk}", flush=True)
            if len(missing_chunks) > 10:
                print(f"[forecast-setup] missing {target} {label}: ... {len(missing_chunks) - 10} more chunks", flush=True)
            if strict_data_preflight:
                failures.append(f"{target} {label} has {len(points)} rows, expected {expected}")

if total_points == 0:
    failures.append("no usable imported data was found for the selected target and forecast windows")

if failures:
    raise SystemExit("Imported data preflight failed: " + "; ".join(failures))
PY
}

wait_for_forecast_data() {
  local started_at
  started_at="$(date +%s)"
  until preflight_forecast_data; do
    if [ $(( $(date +%s) - started_at )) -ge "$import_verify_timeout_seconds" ]; then
      printf '[forecast-setup] timed out waiting for usable imported data after %s seconds\n' "$import_verify_timeout_seconds" >&2
      exit 1
    fi
    printf '[forecast-setup] imported data not usable yet; retrying\n'
    sleep 5
  done
}

resolve_available_training_window() {
  python3 - "$backend_url" "$target" "$train_start" "$train_days" "$forecast_start" "$data_timeout_seconds" "$min_training_days" <<'PY'
from datetime import datetime, timedelta, timezone
import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
target_arg = sys.argv[2]
train_start_arg = sys.argv[3]
requested_train_days = int(sys.argv[4])
forecast_start = datetime.fromisoformat(sys.argv[5].replace("Z", "+00:00")).astimezone(timezone.utc)
timeout_seconds = int(sys.argv[6])
min_training_days = int(sys.argv[7])
targets = ("generation", "consumption") if target_arg == "all" else (target_arg,)
now = datetime.now(timezone.utc)

def format_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def parse_utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

if train_start_arg:
    requested_start = parse_utc(train_start_arg)
elif forecast_start >= now:
    requested_start = parse_utc("2025-06-11T00:00:00Z")
else:
    requested_start = forecast_start - timedelta(days=requested_train_days)
requested_end = requested_start + timedelta(days=requested_train_days)
if forecast_start < now:
    requested_end = forecast_start

first_values = []
last_values = []
row_counts = []
for target in targets:
    params = urlencode({"target": target, "from": format_utc(requested_start), "to": format_utc(requested_end)})
    with urlopen(f"{base_url}/api/forecast-datasets?{params}", timeout=timeout_seconds) as response:
        payload = json.load(response)
    timestamps = sorted(point["timestamp"] for point in payload.get("points", []) if point.get("timestamp"))
    if not timestamps:
        raise SystemExit(f"No usable imported data for {target} in requested training window")
    first_values.append(parse_utc(timestamps[0]))
    last_values.append(parse_utc(timestamps[-1]))
    row_counts.append(len(timestamps))

usable_start = max(first_values)
usable_last = min(last_values)
usable_rows = min(row_counts)
days_by_rows = usable_rows // 96
days_by_range = int(((usable_last + timedelta(minutes=15)) - usable_start).total_seconds() // 86400)
usable_days = min(requested_train_days, days_by_rows, days_by_range)
if usable_days < min_training_days:
    raise SystemExit(f"Only {usable_days} usable training day(s) found; minimum is {min_training_days}")
if usable_days < requested_train_days:
    print(f"TRAIN_START={format_utc(usable_start)}")
    print(f"TRAIN_DAYS={usable_days}")
PY
}

apply_training_window_override() {
  local override
  local override_train_start
  local override_train_days

  if [ -n "$train_start" ] || [ "$strict_data_preflight" = "1" ]; then
    return
  fi

  if ! override="$(resolve_available_training_window)"; then
    printf '[forecast-setup] could not adjust training window automatically; continuing with requested window\n'
    return
  fi
  if [ -z "$override" ]; then
    return
  fi

  while IFS='=' read -r name value; do
    case "$name" in
      TRAIN_START)
        override_train_start="$value"
        ;;
      TRAIN_DAYS)
        override_train_days="$value"
        ;;
    esac
  done <<EOF
$override
EOF
  if [ -n "$override_train_start" ] && [ -n "$override_train_days" ]; then
    train_start="$override_train_start"
    train_days="$override_train_days"
    forecast_args+=(--train-start "$train_start" --train-days "$train_days")
    printf '[forecast-setup] adjusted training window to available imported data: train_start=%s train_days=%s\n' "$train_start" "$train_days"
  fi
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
  if [ -z "$train_start" ]; then
    train_start="$default_train_start"
    forecast_args+=(--train-start "$train_start")
  fi
fi
if [ "$forecast_days_explicit" = "0" ]; then
  forecast_args+=(--forecast-days "$forecast_days")
fi

printf '[forecast-setup] start Docker background services\n'
start_server_stack

if [ "$reset_and_import" = "1" ]; then
  printf '[forecast-setup] reset and import CSV data\n'
  ./reset-and-import-data.sh
  printf '[forecast-setup] restart backend after import\n'
  start_server_stack
fi

printf '[forecast-setup] wait for backend at %s\n' "$backend_url"
wait_for_backend

printf '[forecast-setup] check imported actual data\n'
ensure_imported_data_exists

printf '[forecast-setup] preflight imported forecast data\n'
wait_for_forecast_data
apply_training_window_override

printf '[forecast-setup] backend and data checks passed\n'
printf '[forecast-setup] final forecast args:'
for arg in "${forecast_args[@]}"; do
  printf ' %s' "$arg"
done
printf '\n'
case "$runner_mode" in
  docker)
    printf '[forecast-setup] run forecast batch in Docker\n'
    docker compose --profile forecasts build forecast-runner
    docker compose --profile forecasts run --rm --no-deps forecast-runner --base-url http://backend:8080 "${forecast_args[@]}"
    ;;
  host)
    printf '[forecast-setup] run forecast batch on host\n'
    ./run-all-forecasts.sh --base-url "$backend_url" "${forecast_args[@]}"
    ;;
  *)
    printf '[forecast-setup] invalid FORECAST_RUNNER_MODE: %s\n' "$runner_mode" >&2
    exit 2
    ;;
esac
