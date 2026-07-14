#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"
INFLUX_TABLE="energy_series"
IMPORT_CSV_DIRECTORY="../../data/raw/csv_Archiv_6_2025_bis_5_2026"
INFLUX_TOKEN_FILE="./influxdb/admin-token.json"

INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$INFLUX_TOKEN_FILE")
export INFLUXDB_TOKEN

mkdir -p ./influxdb-explorer/config
cat > ./influxdb-explorer/config/config.json <<EOF
{
  "DEFAULT_INFLUX_SERVER": "http://influxdb:8181",
  "DEFAULT_INFLUX_DATABASE": "$INFLUX_DATABASE",
  "DEFAULT_API_TOKEN": "$INFLUXDB_TOKEN",
  "DEFAULT_SERVER_NAME": "Local InfluxDB 3"
}
EOF

docker compose down
docker compose up -d

until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

POINT_COUNT=$(docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database "$INFLUX_DATABASE" \
  "SELECT count(total) AS point_count FROM $INFLUX_TABLE" \
  --format json 2>/dev/null \
  | tr -cd '0-9' || true)

cd ./backend

if [ -n "$POINT_COUNT" ] && [ "$POINT_COUNT" -gt 0 ]; then
  printf 'Skipping CSV import; %s already contains %s points.\n' "$INFLUX_TABLE" "$POINT_COUNT"
else
  ./mvnw package
  java -Denergy.influx.token="$INFLUXDB_TOKEN" -Denergy.import.command.directory="$IMPORT_CSV_DIRECTORY" -jar target/quarkus-app/quarkus-run.jar
fi

./mvnw -Denergy.influx.token="$INFLUXDB_TOKEN" quarkus:dev
