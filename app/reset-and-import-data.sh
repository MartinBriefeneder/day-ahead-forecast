#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
DEFAULT_IMPORT_DIR="../data/raw/csv_Archiv_6_2025_bis_5_2026"
IMPORT_DIR_INPUT="${1:-$DEFAULT_IMPORT_DIR}"
INFLUX_TOKEN_FILE="./influxdb/admin-token.json"

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s [csv-directory]\n' "$0"
  exit 0
fi

if [ ! -f "$INFLUX_TOKEN_FILE" ]; then
  printf 'Missing InfluxDB token file: %s\nRun ./run-dev.sh once or create the local token file first.\n' "$INFLUX_TOKEN_FILE" >&2
  exit 1
fi

if [ ! -d "$IMPORT_DIR_INPUT" ]; then
  printf 'CSV import directory does not exist: %s\n' "$IMPORT_DIR_INPUT" >&2
  exit 1
fi

IMPORT_DIR=$(realpath "$IMPORT_DIR_INPUT")

INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$INFLUX_TOKEN_FILE")
export INFLUXDB_TOKEN

if [ -z "$INFLUXDB_TOKEN" ]; then
  printf 'Could not read token from %s\n' "$INFLUX_TOKEN_FILE" >&2
  exit 1
fi

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb

printf 'Waiting for InfluxDB...\n'
until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

printf 'Recreating database %s...\n' "$INFLUX_DATABASE"
docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE"

cd ./quarkus
printf 'Packaging backend...\n'
./mvnw -DskipTests package

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
java -Dquarkus.http.host=127.0.0.1 -Dquarkus.http.port=0 -Denergy.influx.token="$INFLUXDB_TOKEN" -Denergy.influx.database="$INFLUX_DATABASE" -Denergy.import.command.directory="$IMPORT_DIR" -jar target/quarkus-app/quarkus-run.jar
printf 'Import complete. Start ./run-dev.sh and open Grafana at http://localhost:3000 for inspection.\n'
