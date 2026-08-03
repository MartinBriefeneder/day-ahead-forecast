#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_DATABASE="energy"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:?set INFLUXDB_TOKEN or create app/.env before running this script}"

mkdir -p ./influxdb-explorer/config
cat > ./influxdb-explorer/config/config.json <<EOF
{
  "DEFAULT_INFLUX_SERVER": "http://influxdb:8181",
  "DEFAULT_INFLUX_DATABASE": "$INFLUX_DATABASE",
  "DEFAULT_API_TOKEN": "$INFLUXDB_TOKEN",
  "DEFAULT_SERVER_NAME": "Local InfluxDB 3"
}
EOF

docker compose --profile server up -d --build

printf 'Backend: http://localhost:8080\n'
printf 'Grafana: http://localhost:3000\n'
printf 'InfluxDB Explorer: http://localhost:8180\n'
