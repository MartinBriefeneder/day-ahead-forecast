#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
IMPORT_DATABASE="energy_import"
IMPORT_DIR="../../data/raw/csv_Archiv_6_2025_bis_5_2026"
EXPECTED_LAST_TIME="2026-05-31T21:45:00"
INFLUX_TOKEN_FILE="./influxdb/admin-token.json"

INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$INFLUX_TOKEN_FILE")
export INFLUXDB_TOKEN

docker compose up -d influxdb

until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$IMPORT_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$IMPORT_DATABASE"

cd ./backend
./mvnw -DskipTests package

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
java -Dquarkus.http.host=127.0.0.1 -Dquarkus.http.port=0 -Denergy.influx.token="$INFLUXDB_TOKEN" -Denergy.influx.database="$IMPORT_DATABASE" -Denergy.import.command.directory="$IMPORT_DIR" -jar target/quarkus-app/quarkus-run.jar

LAST_TIME=$(docker exec influxdb influxdb3 query --database "$IMPORT_DATABASE" \
  --token "$INFLUXDB_TOKEN" \
  "SELECT max(time) AS last_time FROM energy_series" \
  --format json 2>/dev/null \
  | tr -d '[]{}"' \
  | cut -d: -f2- || true)

if [ "$LAST_TIME" != "$EXPECTED_LAST_TIME" ]; then
  printf 'Import did not reach expected last timestamp. Expected %s, got %s. Keeping existing %s database.\n' "$EXPECTED_LAST_TIME" "${LAST_TIME:-none}" "$INFLUX_DATABASE" >&2
  exit 1
fi

docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE"
docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database "$IMPORT_DATABASE" \
  "INSERT INTO $INFLUX_DATABASE.energy_series SELECT * FROM energy_series"
docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$IMPORT_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
