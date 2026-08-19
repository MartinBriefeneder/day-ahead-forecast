#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
FORECAST_MEASUREMENTS="energy_forecasts forecast_evaluations forecast_run_metadata"
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

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s\n' "$0"
  printf 'Deletes stored forecast tables from InfluxDB and keeps imported actuals.\n'
  exit 0
fi

wait_for_influx() {
  attempts=0
  until docker compose exec -T influxdb influx ping --host http://localhost:8086 >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$INFLUX_WAIT_SECONDS" ]; then
      printf 'Timed out waiting for InfluxDB after %s seconds. Check Docker and INFLUXDB_TOKEN.\n' "$INFLUX_WAIT_SECONDS" >&2
      exit 1
    fi
    sleep 1
  done
}

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb

printf 'Waiting for InfluxDB...\n'
wait_for_influx

DELETE_STOP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf 'Deleting stored forecast measurements from bucket %s in org %s...\n' "$INFLUXDB_BUCKET" "$INFLUXDB_ORG"
for measurement in $FORECAST_MEASUREMENTS; do
  if docker compose exec -T influxdb influx delete \
    --bucket "$INFLUXDB_BUCKET" \
    --org "$INFLUXDB_ORG" \
    --token "$INFLUXDB_TOKEN" \
    --start 1970-01-01T00:00:00Z \
    --stop "$DELETE_STOP" \
    --predicate "_measurement=\"$measurement\"" >/dev/null 2>&1; then
    printf 'Deleted %s.\n' "$measurement"
  else
    printf 'Skipped %s. It may not exist.\n' "$measurement"
  fi
done

printf 'Forecast reset complete. Imported actuals in energy_values were not changed.\n'
