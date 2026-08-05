#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_DATABASE="energy"
INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
export INFLUXDB_TOKEN=apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg

wait_for_influx() {
  attempts=0
  until docker compose exec -T influxdb influxdb3 query --token "$INFLUXDB_TOKEN" --database _internal "SHOW TABLES" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$INFLUX_WAIT_SECONDS" ]; then
      printf 'Timed out waiting for InfluxDB after %s seconds. Check Docker and INFLUXDB_TOKEN.\n' "$INFLUX_WAIT_SECONDS" >&2
      exit 1
    fi
    sleep 1
  done
}

mkdir -p ./influxdb-explorer/config
cat > ./influxdb-explorer/config/config.json <<EOF
{
  "DEFAULT_INFLUX_SERVER": "http://influxdb:8181",
  "DEFAULT_INFLUX_DATABASE": "$INFLUX_DATABASE",
  "DEFAULT_API_TOKEN": "$INFLUXDB_TOKEN",
  "DEFAULT_SERVER_NAME": "Local InfluxDB 3"
}
EOF

docker compose --profile server stop backend >/dev/null 2>&1 || true
docker compose up -d influxdb influxdb-init grafana influxdb3-explorer

printf 'Waiting for InfluxDB...\n'
wait_for_influx

cd ./quarkus
./mvnw -Denergy.influx.token="$INFLUXDB_TOKEN" quarkus:dev
