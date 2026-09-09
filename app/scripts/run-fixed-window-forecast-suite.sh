#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf 'Usage: %s\n' "$0" >&2
  printf 'This fixed-window suite does not accept parameters. Edit the constants in the script if the windows must change.\n' >&2
  exit 2
fi

SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
APP_DIR="$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${FORECAST_BACKEND_URL:-http://localhost:8080}"

BACKTEST_TRAIN_DAYS="90"
BACKTEST_FORECAST_START="2026-06-11T21:15:00Z"
BACKTEST_FORECAST_DAYS="7"
BACKTEST_FORECAST_END="2026-06-18T21:15:00Z"

LIVE_TRAIN_DAYS="90"
LIVE_FORECAST_START="2026-09-08T11:15:00Z"
LIVE_FORECAST_DAYS="7"
LIVE_FORECAST_END="2026-09-15T11:15:00Z"

REPORT_DIR="$APP_DIR/reports/forecast-runs"
LOG_DIR="$REPORT_DIR/logs"
RUN_TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"

run_logged() {
  local label="$1"
  local log_file="$LOG_DIR/${RUN_TIMESTAMP}-${label}.log"
  shift

  printf 'Run %s; log: %s\n' "$label" "$log_file"
  "$@" 2>&1 | tee "$log_file"
}

backtest_metrics() {
  cd "$APP_DIR/python"
  if [ -d .venv ]; then
    . .venv/bin/activate
  fi
  python3 export_forecast_metrics.py --base-url "$BASE_URL" --target generation --forecast-start "$BACKTEST_FORECAST_START" --forecast-end "$BACKTEST_FORECAST_END" --aggregate
  python3 export_forecast_metrics.py --base-url "$BASE_URL" --target consumption --forecast-start "$BACKTEST_FORECAST_START" --forecast-end "$BACKTEST_FORECAST_END" --aggregate
}

printf 'Check backend at %s\n' "$BASE_URL"
if ! curl -fsS "$BASE_URL/api/energy-import/status" >/dev/null; then
  printf 'Backend is not reachable or imported data is unavailable. Start it from app/ with ./run-dev.sh or ./run-server.sh.\n' >&2
  exit 1
fi

mkdir -p "$REPORT_DIR" "$LOG_DIR"

printf 'Run live forecast suite: %s to %s\n' "$LIVE_FORECAST_START" "$LIVE_FORECAST_END"
run_logged live-saved-models env \
  FORECAST_RUN_LGBM=1 \
  FORECAST_RUN_ENSEMBLE=1 \
  FORECAST_RUN_FUTURE_XGBOOST=1 \
  FORECAST_BATCH_CONTINUE_ON_ERROR=0 \
  "$APP_DIR/run-forecasts.sh" \
    --target all \
    --base-url "$BASE_URL" \
    --train-days "$LIVE_TRAIN_DAYS" \
    --forecast-start "$LIVE_FORECAST_START" \
    --forecast-days "$LIVE_FORECAST_DAYS"

printf 'Run backtest forecast suite: %s to %s\n' "$BACKTEST_FORECAST_START" "$BACKTEST_FORECAST_END"
run_logged backtest-saved-models env \
  FORECAST_RUN_LGBM=1 \
  FORECAST_RUN_ENSEMBLE=1 \
  FORECAST_RUN_FUTURE_XGBOOST=0 \
  FORECAST_BATCH_CONTINUE_ON_ERROR=0 \
  "$APP_DIR/run-forecasts.sh" \
    --target all \
    --base-url "$BASE_URL" \
    --train-days "$BACKTEST_TRAIN_DAYS" \
    --forecast-start "$BACKTEST_FORECAST_START" \
    --forecast-days "$BACKTEST_FORECAST_DAYS"

printf 'Run backtest metric exports\n'
run_logged backtest-metrics backtest_metrics

printf 'Done\n'
