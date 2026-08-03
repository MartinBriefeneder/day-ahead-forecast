#!/usr/bin/env sh
set -eu

INFLUX_DATABASE="energy"

: "${INFLUXDB_TOKEN:?export INFLUXDB_TOKEN before running this script}"

mkdir -p ./influxdb-explorer/config
cat > ./influxdb-explorer/config/config.json <<EOF
{
  "DEFAULT_INFLUX_SERVER": "http://influxdb:8181",
  "DEFAULT_INFLUX_DATABASE": "$INFLUX_DATABASE",
  "DEFAULT_API_TOKEN": "$INFLUXDB_TOKEN",
  "DEFAULT_SERVER_NAME": "Local InfluxDB 3"
}
EOF

docker compose up -d

until docker exec influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
  sleep 1
done

cd ./quarkus
./mvnw -Denergy.influx.token="$INFLUXDB_TOKEN" quarkus:dev
