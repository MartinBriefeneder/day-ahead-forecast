#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
IMPORT_DIR="../../data/raw/csv_Archiv_6_2025_bis_5_2026"
INFLUX_TOKEN_FILE="./influxdb/admin-token.json"

INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$INFLUX_TOKEN_FILE")
export INFLUXDB_TOKEN

docker compose up -d influxdb

until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

docker exec influxdb influxdb3 delete database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE" --hard-delete now --yes >/dev/null 2>&1 || true
docker exec influxdb influxdb3 create database --token "$INFLUXDB_TOKEN" "$INFLUX_DATABASE"

cd ./backend
./mvnw -DskipTests package

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
java -Dquarkus.http.host=127.0.0.1 -Dquarkus.http.port=0 -Denergy.influx.token="$INFLUXDB_TOKEN" -Denergy.influx.database="$INFLUX_DATABASE" -Denergy.import.command.directory="$IMPORT_DIR" -jar target/quarkus-app/quarkus-run.jar
