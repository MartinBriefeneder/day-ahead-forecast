#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_DATABASE="energy"
INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
FORECAST_TABLES="energy_forecasts forecast_evaluations forecast_run_metadata"
DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:=$DEFAULT_INFLUXDB_TOKEN}"
export INFLUXDB_TOKEN

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s\n' "$0"
  printf 'Deletes stored forecast tables from InfluxDB and keeps imported actuals.\n'
  exit 0
fi

wait_for_influx() {
  attempts=0
  until docker compose exec -T influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$INFLUX_WAIT_SECONDS" ]; then
      printf 'Timed out waiting for InfluxDB after %s seconds. Check Docker and INFLUXDB_TOKEN.\n' "$INFLUX_WAIT_SECONDS" >&2
      exit 1
    fi
    sleep 1
  done
}

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb influxdb-init

printf 'Waiting for InfluxDB...\n'
wait_for_influx

printf 'Deleting stored forecast tables from database %s...\n' "$INFLUX_DATABASE"
for table in $FORECAST_TABLES; do
  if docker compose exec -T influxdb influxdb3 delete table --token "$INFLUXDB_TOKEN" --database "$INFLUX_DATABASE" --hard-delete now "$table" >/dev/null 2>&1; then
    printf 'Deleted %s.\n' "$table"
  else
    printf 'Skipped %s. It may not exist.\n' "$table"
  fi
done

printf 'Forecast reset complete. Imported actuals in energy_values were not changed.\n'
