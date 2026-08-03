#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_DATABASE="energy"
INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
DEFAULT_IMPORT_DIR="./quarkus/data/csv_Archiv"
IMPORT_DIR_INPUT="${1:-$DEFAULT_IMPORT_DIR}"

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s [csv-directory]\n' "$0"
  exit 0
fi

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:?set INFLUXDB_TOKEN or create app/.env before running this script}"

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

if [ ! -d "$IMPORT_DIR_INPUT" ]; then
  printf 'CSV import directory does not exist: %s\n' "$IMPORT_DIR_INPUT" >&2
  exit 1
fi

IMPORT_DIR=$(realpath "$IMPORT_DIR_INPUT")

docker compose --profile server stop backend >/dev/null 2>&1 || true

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb influxdb-init

printf 'Waiting for InfluxDB...\n'
wait_for_influx

printf 'Recreating database %s...\n' "$INFLUX_DATABASE"
docker compose exec -T influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker compose exec -T influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE"

printf 'Building backend image...\n'
docker compose --profile server build backend

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
docker compose --profile server run --rm --no-deps \
  --volume "$IMPORT_DIR:/import-data:ro" \
  --entrypoint java \
  backend \
  -Dquarkus.http.host=127.0.0.1 \
  -Dquarkus.http.port=0 \
  -Denergy.influx.token="$INFLUXDB_TOKEN" \
  -Denergy.influx.database="$INFLUX_DATABASE" \
  -Denergy.import.command.directory=/import-data \
  -jar quarkus-run.jar
printf 'Import complete. Run ./run-dev.sh for development or ./run-server.sh for the Docker backend.\n'
