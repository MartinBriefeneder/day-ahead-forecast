#!/usr/bin/env bash
set -euo pipefail

script_dir="$(dirname "$0")"
train_start=""
train_days="90"
forecast_start=""
forecast_days="7"
target="all"
base_url="${FORECAST_BACKEND_URL:-http://localhost:8080}"
continue_on_error="${FORECAST_BATCH_CONTINUE_ON_ERROR:-1}"
default_train_start="${FORECAST_DEFAULT_TRAIN_START:-2025-06-11T00:00:00Z}"
failed_steps=0
successful_steps=0
successful_forecast_steps=0

usage() {
  printf 'Usage: %s [--target generation|consumption|all] [--base-url URL] [--train-start ISO] [--train-days DAYS] [--forecast-start ISO] [--forecast-days DAYS]\n' "$0"
  printf 'Defaults: --target all --train-days 90 --forecast-start next-quarter-hour --forecast-days 7\n'
  printf 'Plain runs also use FORECAST_DEFAULT_TRAIN_START when --train-start is omitted.\n'
  printf 'Set FORECAST_BATCH_CONTINUE_ON_ERROR=0 to stop after the first failed forecast step.\n'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      target="$2"
      shift 2
      ;;
    --base-url)
      base_url="$2"
      shift 2
      ;;
    --train-start)
      train_start="$2"
      shift 2
      ;;
    --train-days)
      train_days="$2"
      shift 2
      ;;
    --forecast-start)
      forecast_start="$2"
      shift 2
      ;;
    --forecast-days)
      forecast_days="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

case "$target" in
  generation|consumption)
    targets=("$target")
    ;;
  all)
    targets=(generation consumption)
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [ -z "$forecast_start" ]; then
  forecast_start="$(python3 -c 'from datetime import datetime, timedelta, timezone; now = datetime.now(timezone.utc).replace(second=0, microsecond=0); minute = (now.minute // 15 + 1) * 15; value = now.replace(minute=0) + timedelta(hours=1) if minute == 60 else now.replace(minute=minute); print(value.isoformat().replace("+00:00", "Z"))')"
  if [ -z "$train_start" ]; then
    train_start="$default_train_start"
  fi
fi

forecast_end="$(python3 -c 'from datetime import datetime, timedelta, timezone; import sys; print((datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(days=int(sys.argv[2]))).isoformat().replace("+00:00", "Z"))' "$forecast_start" "$forecast_days")"

cd "$script_dir/python"
export PYTHONUNBUFFERED=1

run_forecast_step() {
  local label="$1"
  local status
  shift
  printf '[forecast-batch] start %s\n' "$label"
  if "$@"; then
    successful_steps=$((successful_steps + 1))
    case "$label" in
      compare-*)
        ;;
      *)
        successful_forecast_steps=$((successful_forecast_steps + 1))
        ;;
    esac
    printf '[forecast-batch] done %s\n' "$label"
    return 0
  fi

  status="$?"
  failed_steps=$((failed_steps + 1))
  printf '[forecast-batch] failed %s exit=%s\n' "$label" "$status" >&2
  case "$continue_on_error" in
    1|true|TRUE|yes|YES)
      printf '[forecast-batch] continue after failed step %s\n' "$label" >&2
      return 0
      ;;
    *)
      return "$status"
      ;;
  esac
}

if [ "${FORECAST_SKIP_VENV:-0}" != "1" ]; then
  if [ ! -d .venv ]; then
    printf '[forecast-batch] create Python virtual environment\n'
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  printf '[forecast-batch] install Python requirements\n'
  pip install -r requirements.txt
else
  printf '[forecast-batch] use container Python environment\n'
fi
printf '[forecast-batch] forecast_start=%s forecast_end=%s forecast_days=%s target=%s base_url=%s\n' "$forecast_start" "$forecast_end" "$forecast_days" "$target" "$base_url"

for current_target in "${targets[@]}"; do
  common_args=(--base-url "$base_url" --target "$current_target" --train-days "$train_days" --forecast-start "$forecast_start" --forecast-days "$forecast_days")
  if [ -n "$train_start" ]; then
    common_args+=(--train-start "$train_start")
  fi

  printf '[forecast-batch] target=%s\n' "$current_target"
  run_forecast_step "weekly-persistence $current_target" python3 main.py "${common_args[@]}" --save
  run_forecast_step "default-openstef-xgboost $current_target" python3 default_openstef_xgboost.py "${common_args[@]}"
  run_forecast_step "tuned-openstef-xgboost $current_target" python3 tuned_openstef.py "${common_args[@]}"
  run_forecast_step "custom-openstef $current_target" python3 custom_openstef.py "${common_args[@]}"
  run_forecast_step "compare-window $current_target" python3 compare_forecasts.py --base-url "$base_url" --target "$current_target" --forecast-start "$forecast_start" --forecast-end "$forecast_end"
  run_forecast_step "compare-all-saved $current_target" python3 compare_forecasts.py --base-url "$base_url" --target "$current_target" --all-saved
done

if [ "$failed_steps" -gt 0 ]; then
  printf '[forecast-batch] completed with failed_steps=%s successful_steps=%s successful_forecast_steps=%s\n' "$failed_steps" "$successful_steps" "$successful_forecast_steps" >&2
fi
if [ "$successful_forecast_steps" -eq 0 ]; then
  printf '[forecast-batch] no forecast step completed successfully\n' >&2
  exit 1
fi
