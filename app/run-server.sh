#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_DATABASE="energy"
DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:=$DEFAULT_INFLUXDB_TOKEN}"
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

printf 'Building backend image...\n'
docker build -t day-ahead-forecast-backend ./quarkus

docker compose --profile server up -d

printf 'Backend: http://localhost:8080\n'
printf 'Grafana: http://localhost:3000\n'
printf 'InfluxDB Explorer: http://localhost:8180\n'
