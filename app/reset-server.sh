#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${INFLUXDB_TOKEN:=$DEFAULT_INFLUXDB_TOKEN}"
: "${INFLUXDB_ORG:=kirchdorf}"
: "${INFLUXDB_BUCKET:=energy}"
export INFLUXDB_TOKEN INFLUXDB_ORG INFLUXDB_BUCKET

printf 'Resetting backend and Grafana. InfluxDB is preserved.\n'
docker compose --profile server stop backend grafana
docker compose --profile server rm -f backend grafana
docker volume rm day-ahead-forecast_grafana-data >/dev/null 2>&1 || true
docker compose --profile server up -d --build --no-deps --force-recreate backend grafana

printf 'Backend: http://localhost:8080\n'
printf 'Grafana: http://localhost:3000\n'
printf 'InfluxDB preserved: http://localhost:8086\n'
