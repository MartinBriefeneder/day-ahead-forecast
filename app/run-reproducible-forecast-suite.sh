#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf 'Usage: %s\n' "$0" >&2
  printf 'This reproducible suite does not accept parameters. Edit the constants in the script if the fixed windows must change.\n' >&2
  exit 2
fi

SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
BASE_URL="${FORECAST_BACKEND_URL:-http://localhost:8080}"

BACKTEST_TRAIN_DAYS="90"
BACKTEST_FORECAST_START="2026-06-11T21:15:00Z"
BACKTEST_FORECAST_DAYS="7"
BACKTEST_FORECAST_END="2026-06-18T21:15:00Z"

FUTURE_TRAIN_DAYS="90"
FUTURE_FORECAST_START="2026-09-08T11:15:00Z"
FUTURE_FORECAST_DAYS="7"
FUTURE_FORECAST_END="2026-09-15T11:15:00Z"

REPORT_DIR="$SCRIPT_DIR/reports/forecast-runs"
MANIFEST="$REPORT_DIR/reproducible-forecast-suite-manifest.md"

printf 'Check backend at %s\n' "$BASE_URL"
if ! curl -fsS "$BASE_URL/api/energy-import/status" >/dev/null; then
  printf 'Backend is not reachable or imported data is unavailable. Start it from app/ with ./run-dev.sh or ./run-server.sh.\n' >&2
  exit 1
fi

mkdir -p "$REPORT_DIR"

printf 'Run future forecast suite: %s to %s\n' "$FUTURE_FORECAST_START" "$FUTURE_FORECAST_END"
FORECAST_RUN_LGBM=1 \
FORECAST_RUN_ENSEMBLE=1 \
FORECAST_BATCH_CONTINUE_ON_ERROR=0 \
"$SCRIPT_DIR/run-forecasts.sh" \
  --target all \
  --base-url "$BASE_URL" \
  --train-days "$FUTURE_TRAIN_DAYS" \
  --forecast-start "$FUTURE_FORECAST_START" \
  --forecast-days "$FUTURE_FORECAST_DAYS"

printf 'Run future quantile reports\n'
(
  cd "$SCRIPT_DIR/python"
  if [ -d .venv ]; then
    . .venv/bin/activate
  fi
  python3 quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target generation --train-days "$FUTURE_TRAIN_DAYS" --forecast-start "$FUTURE_FORECAST_START" --forecast-days "$FUTURE_FORECAST_DAYS"
  python3 quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target consumption --train-days "$FUTURE_TRAIN_DAYS" --forecast-start "$FUTURE_FORECAST_START" --forecast-days "$FUTURE_FORECAST_DAYS"
)

printf 'Run backtest forecast suite: %s to %s\n' "$BACKTEST_FORECAST_START" "$BACKTEST_FORECAST_END"
FORECAST_RUN_LGBM=1 \
FORECAST_RUN_ENSEMBLE=1 \
FORECAST_BATCH_CONTINUE_ON_ERROR=0 \
"$SCRIPT_DIR/run-forecasts.sh" \
  --target all \
  --base-url "$BASE_URL" \
  --train-days "$BACKTEST_TRAIN_DAYS" \
  --forecast-start "$BACKTEST_FORECAST_START" \
  --forecast-days "$BACKTEST_FORECAST_DAYS"

printf 'Run backtest quantile reports and metric exports\n'
(
  cd "$SCRIPT_DIR/python"
  if [ -d .venv ]; then
    . .venv/bin/activate
  fi
  python3 quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target generation --train-days "$BACKTEST_TRAIN_DAYS" --forecast-start "$BACKTEST_FORECAST_START" --forecast-days "$BACKTEST_FORECAST_DAYS"
  python3 quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target consumption --train-days "$BACKTEST_TRAIN_DAYS" --forecast-start "$BACKTEST_FORECAST_START" --forecast-days "$BACKTEST_FORECAST_DAYS"
  python3 export_forecast_metrics.py --base-url "$BASE_URL" --target generation --forecast-start "$BACKTEST_FORECAST_START" --forecast-end "$BACKTEST_FORECAST_END" --aggregate
  python3 export_forecast_metrics.py --base-url "$BASE_URL" --target consumption --forecast-start "$BACKTEST_FORECAST_START" --forecast-end "$BACKTEST_FORECAST_END" --aggregate
)

cat > "$MANIFEST" <<EOF
# Reproducible Forecast Suite Manifest

Generated at: $(date -u '+%Y-%m-%dT%H:%M:%SZ')

## Fixed Windows

- Future forecast window: \`$FUTURE_FORECAST_START\` to \`$FUTURE_FORECAST_END\`.
- Future train days: \`$FUTURE_TRAIN_DAYS\`.
- Backtest forecast window: \`$BACKTEST_FORECAST_START\` to \`$BACKTEST_FORECAST_END\`.
- Backtest train days: \`$BACKTEST_TRAIN_DAYS\`.

## Covered Targets

- \`generation\`
- \`consumption\`

## Covered Saved Forecast Models

- \`weekly-persistence\`
- \`openstef-default-xgboost\`
- \`openstef-xgboost-tuned\`
- \`openstef-lgbm\`
- \`openstef-custom-ensemble\`

## Covered Local Report-Only Forecast

- \`openstef-xgboost-quantile-calibrated\` with p10, p50, and p90.

## Output Location

- \`app/reports/forecast-runs/\`

## Notes

- The future suite uses Gridoo forecast weather for weather-dependent OpenSTEF prediction windows.
- The backtest suite uses observed historical weather from the local workbook.
- Quantile forecast values are not persisted to the backend in the current implementation.
EOF

printf 'Wrote manifest %s\n' "$MANIFEST"
printf 'Done\n'
