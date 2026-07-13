#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
INFLUX_TABLE="energy_series"
IMPORT_CSV="src/main/resources/csv_Archiv_6_2025_bis_5_2026/RC105812_2025_6.csv"

docker compose down
docker compose up -d

until docker exec influxdb influxdb3 query --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

docker exec influxdb influxdb3 create database "$INFLUX_DATABASE" >/dev/null 2>&1 || true

POINT_COUNT=$(docker exec influxdb influxdb3 query --database "$INFLUX_DATABASE" \
  "SELECT count(total) AS point_count FROM $INFLUX_TABLE" \
  --format json 2>/dev/null \
  | tr -cd '0-9' || true)

cd ./backend

if [ -n "$POINT_COUNT" ] && [ "$POINT_COUNT" -gt 0 ]; then
  printf 'Skipping CSV import; %s already contains %s points.\n' "$INFLUX_TABLE" "$POINT_COUNT"
else
  ./mvnw package
  java -Denergy.import.command.file="$IMPORT_CSV" -jar target/quarkus-app/quarkus-run.jar
fi

./mvnw quarkus:dev
