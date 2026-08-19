#!/usr/bin/env bash
set -euo pipefail

script_dir="$(dirname "$0")"
train_start=""
train_days="90"
forecast_start=""
forecast_days="7"
target="all"

usage() {
  printf 'Usage: %s [--target generation|consumption|all] [--train-start ISO] [--train-days DAYS] [--forecast-start ISO] [--forecast-days DAYS]\n' "$0"
  printf 'Defaults: --target all --train-days 90 --forecast-start next-quarter-hour --forecast-days 7\n'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      target="$2"
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
fi

forecast_end="$(python3 -c 'from datetime import datetime, timedelta, timezone; import sys; print((datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(days=int(sys.argv[2]))).isoformat().replace("+00:00", "Z"))' "$forecast_start" "$forecast_days")"

cd "$script_dir/python"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

for current_target in "${targets[@]}"; do
  common_args=(--target "$current_target" --train-days "$train_days" --forecast-start "$forecast_start" --forecast-days "$forecast_days")
  if [ -n "$train_start" ]; then
    common_args+=(--train-start "$train_start")
  fi

  python3 main.py "${common_args[@]}" --save
  python3 default_openstef_xgboost.py "${common_args[@]}"
  python3 tuned_openstef.py "${common_args[@]}"
  python3 custom_openstef.py "${common_args[@]}"
  python3 compare_forecasts.py --target "$current_target" --forecast-start "$forecast_start" --forecast-end "$forecast_end"
done
