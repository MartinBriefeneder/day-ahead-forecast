#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"
START_STACK="${ENERGY_AVAILABILITY_START_STACK:-1}"
BACKEND_URL="${AVAILABILITY_BACKEND_URL:-http://localhost:8080}"
INFLUX_URL="${AVAILABILITY_INFLUX_URL:-http://localhost:8086}"
GRAFANA_URL="${AVAILABILITY_GRAFANA_URL:-http://localhost:3000}"
TIMEOUT_SECONDS="${AVAILABILITY_TIMEOUT_SECONDS:-90}"

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
  printf 'Usage: %s\n' "$0"
  printf 'Starts the local stack and runs opt-in end-to-end availability tests.\n'
  printf 'Set ENERGY_AVAILABILITY_START_STACK=0 to test an already running stack.\n'
  exit 0
fi

if [ "$START_STACK" != "0" ]; then
  ./run-server.sh
fi

cd ./quarkus
./mvnw \
  -DskipITs=false \
  -Davailability.test=true \
  -Dtest=NoUnitTests \
  -Dsurefire.failIfNoSpecifiedTests=false \
  -Dit.test=BackendAvailabilityIT \
  -Davailability.backend-url="$BACKEND_URL" \
  -Davailability.influx-url="$INFLUX_URL" \
  -Davailability.grafana-url="$GRAFANA_URL" \
  -Davailability.timeout-seconds="$TIMEOUT_SECONDS" \
  verify
