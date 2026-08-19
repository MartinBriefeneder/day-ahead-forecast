#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
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

wait_for_influx() {
  attempts=0
  until docker compose exec -T influxdb influx ping --host http://localhost:8086 >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$INFLUX_WAIT_SECONDS" ]; then
      printf 'Timed out waiting for InfluxDB after %s seconds. Check Docker and INFLUXDB_TOKEN.\n' "$INFLUX_WAIT_SECONDS" >&2
      exit 1
    fi
    sleep 1
  done
}

docker compose --profile server stop backend >/dev/null 2>&1 || true
docker compose up -d influxdb grafana

printf 'Waiting for InfluxDB...\n'
wait_for_influx

cd ./quarkus
./mvnw \
  -Denergy.influx.url=http://localhost:8086 \
  -Denergy.influx.token="$INFLUXDB_TOKEN" \
  -Denergy.influx.org="$INFLUXDB_ORG" \
  -Denergy.influx.bucket="$INFLUXDB_BUCKET" \
  quarkus:dev
