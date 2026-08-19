#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

INFLUX_WAIT_SECONDS="${INFLUX_WAIT_SECONDS:-60}"
ENERGY_IMPORT_BUILD="${ENERGY_IMPORT_BUILD:-auto}"
ENERGY_IMPORT_WRITE_BATCH_SIZE="${ENERGY_IMPORT_WRITE_BATCH_SIZE:-50000}"
ENERGY_IMPORT_GZIP_THRESHOLD_BYTES="${ENERGY_IMPORT_GZIP_THRESHOLD_BYTES:-1048576}"
DEFAULT_IMPORT_DIR="./quarkus/data/csv_Archiv"
IMPORT_DIR_INPUT="${1:-$DEFAULT_IMPORT_DIR}"
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

if [ "${1:-}" = "--help" ]; then
  printf 'Usage: %s [csv-directory]\n' "$0"
  exit 0
fi

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

if [ ! -d "$IMPORT_DIR_INPUT" ]; then
  printf 'CSV import directory does not exist: %s\n' "$IMPORT_DIR_INPUT" >&2
  exit 1
fi

IMPORT_DIR=$(realpath "$IMPORT_DIR_INPUT")

should_build_backend() {
  case "$ENERGY_IMPORT_BUILD" in
    1|true|yes|always)
      return 0
      ;;
    0|false|no|never|skip)
      return 1
      ;;
    auto)
      ! docker image inspect day-ahead-forecast-backend >/dev/null 2>&1
      return
      ;;
    *)
      printf 'Invalid ENERGY_IMPORT_BUILD value: %s. Use auto, 1, or 0.\n' "$ENERGY_IMPORT_BUILD" >&2
      exit 1
      ;;
  esac
}

docker compose --profile server stop backend >/dev/null 2>&1 || true

printf 'Starting InfluxDB...\n'
docker compose up -d influxdb

printf 'Waiting for InfluxDB...\n'
wait_for_influx

printf 'Recreating bucket %s in org %s...\n' "$INFLUXDB_BUCKET" "$INFLUXDB_ORG"
docker compose exec -T influxdb influx bucket delete \
  --name "$INFLUXDB_BUCKET" \
  --org "$INFLUXDB_ORG" \
  --token "$INFLUXDB_TOKEN" >/dev/null 2>&1 || true
docker compose exec -T influxdb influx bucket create \
  --name "$INFLUXDB_BUCKET" \
  --org "$INFLUXDB_ORG" \
  --token "$INFLUXDB_TOKEN" >/dev/null

if should_build_backend; then
  printf 'Building backend image...\n'
  docker compose --profile server build backend
fi

printf 'Importing CSV files from %s\n' "$IMPORT_DIR"
docker compose --profile server run --rm --no-deps \
  --volume "$IMPORT_DIR:/import-data:ro" \
  --entrypoint java \
  backend \
  -Dquarkus.http.host=127.0.0.1 \
  -Dquarkus.http.port=0 \
  -Denergy.influx.token="$INFLUXDB_TOKEN" \
  -Denergy.influx.url=http://influxdb:8086 \
  -Denergy.influx.org="$INFLUXDB_ORG" \
  -Denergy.influx.bucket="$INFLUXDB_BUCKET" \
  -Denergy.influx.write-batch-size="$ENERGY_IMPORT_WRITE_BATCH_SIZE" \
  -Denergy.influx.gzip-threshold-bytes="$ENERGY_IMPORT_GZIP_THRESHOLD_BYTES" \
  -Denergy.import.command.directory=/import-data \
  -jar quarkus-run.jar
