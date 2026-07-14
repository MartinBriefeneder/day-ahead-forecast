#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
IMPORT_DATABASE="energy_import"
IMPORT_DIR="src/main/resources/csv_Archiv_6_2025_bis_5_2026"
EXPECTED_LAST_TIME="2026-05-31T21:45:00"

docker compose up -d influxdb

until docker exec influxdb influxdb3 query --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

docker exec influxdb influxdb3 delete database "$IMPORT_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database "$IMPORT_DATABASE"

cd ./backend
./mvnw -DskipTests package

for IMPORT_CSV in \
  "$IMPORT_DIR"/RC105812_2025_6.csv \
  "$IMPORT_DIR"/RC105812_2025_7.csv \
  "$IMPORT_DIR"/RC105812_2025_8.csv \
  "$IMPORT_DIR"/RC105812_2025_9.csv \
  "$IMPORT_DIR"/RC105812_2025_10.csv \
  "$IMPORT_DIR"/RC105812_2025_11.csv \
  "$IMPORT_DIR"/RC105812_2025_12.csv \
  "$IMPORT_DIR"/RC105812_2026_1.csv \
  "$IMPORT_DIR"/RC105812_2026_2.csv \
  "$IMPORT_DIR"/RC105812_2026_3.csv \
  "$IMPORT_DIR"/RC105812_2026_4.csv \
  "$IMPORT_DIR"/RC105812_2026_5.csv; do
  printf 'Importing %s\n' "$IMPORT_CSV"
  java -Dquarkus.http.host=127.0.0.1 -Dquarkus.http.port=0 -Denergy.influx.database="$IMPORT_DATABASE" -Denergy.import.command.file="$IMPORT_CSV" -jar target/quarkus-app/quarkus-run.jar
done

LAST_TIME=$(docker exec influxdb influxdb3 query --database "$IMPORT_DATABASE" \
  "SELECT max(time) AS last_time FROM energy_series" \
  --format json 2>/dev/null \
  | tr -d '[]{}"' \
  | cut -d: -f2- || true)

if [ "$LAST_TIME" != "$EXPECTED_LAST_TIME" ]; then
  printf 'Import did not reach expected last timestamp. Expected %s, got %s. Keeping existing %s database.\n' "$EXPECTED_LAST_TIME" "${LAST_TIME:-none}" "$INFLUX_DATABASE" >&2
  exit 1
fi

docker exec influxdb influxdb3 delete database "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database "$INFLUX_DATABASE"
docker exec influxdb influxdb3 query --database "$IMPORT_DATABASE" \
  "INSERT INTO $INFLUX_DATABASE.energy_series SELECT * FROM energy_series"
docker exec influxdb influxdb3 delete database "$IMPORT_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
