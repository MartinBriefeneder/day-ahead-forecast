#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
DEFAULT_IMPORT_DIR="./quarkus/data/csv_Archiv"
IMPORT_DIR_INPUT="${1:-$DEFAULT_IMPORT_DIR}"

: "${INFLUXDB_TOKEN:?export INFLUXDB_TOKEN before running this script}"

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s [csv-directory]\n' "$0"
  exit 0
fi

if [ ! -d "$IMPORT_DIR_INPUT" ]; then
  printf 'CSV import directory does not exist: %s\n' "$IMPORT_DIR_INPUT" >&2
  exit 1
fi

IMPORT_DIR=$(realpath "$IMPORT_DIR_INPUT")

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb

printf 'Waiting for InfluxDB...\n'
until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

printf 'Recreating database %s...\n' "$INFLUX_DATABASE"
docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE"

printf 'Building backend image...\n'
docker compose build backend

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
docker compose run --rm \
  --volume "$IMPORT_DIR:/import-data:ro" \
  --entrypoint java \
  backend \
  -Dquarkus.http.host=127.0.0.1 \
  -Dquarkus.http.port=0 \
  -Denergy.influx.token="$INFLUXDB_TOKEN" \
  -Denergy.influx.database="$INFLUX_DATABASE" \
  -Denergy.import.command.directory=/import-data \
  -jar quarkus-run.jar
printf 'Import complete. Run docker compose up -d --build and open Grafana at http://localhost:3000 for inspection.\n'
