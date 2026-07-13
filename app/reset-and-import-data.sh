#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
IMPORT_CSV="src/main/resources/csv_Archiv_6_2025_bis_5_2026/RC105812_2025_6.csv"

docker compose up -d influxdb

until docker exec influxdb influxdb3 query --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

docker exec influxdb influxdb3 delete database "$INFLUX_DATABASE" >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database "$INFLUX_DATABASE"

cd ./backend
./mvnw package
java -Denergy.import.command.file="$IMPORT_CSV" -jar target/quarkus-app/quarkus-run.jar
