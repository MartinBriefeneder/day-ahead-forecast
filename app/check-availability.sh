#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

DEFAULT_INFLUXDB_TOKEN="apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg"
START_STACK="${ENERGY_AVAILABILITY_START_STACK:-1}"
BACKEND_URL="${AVAILABILITY_BACKEND_URL:-http://backend:8080}"
INFLUX_URL="${AVAILABILITY_INFLUX_URL:-http://influxdb:8086}"
GRAFANA_URL="${AVAILABILITY_GRAFANA_URL:-http://grafana:3000}"
TIMEOUT_SECONDS="${AVAILABILITY_TIMEOUT_SECONDS:-90}"
MAVEN_IMAGE="${AVAILABILITY_MAVEN_IMAGE:-maven:3.9-eclipse-temurin-21}"
MAVEN_REPOSITORY="${AVAILABILITY_MAVEN_REPOSITORY:-$HOME/.m2/repository}"
COMPOSE_NETWORK="${AVAILABILITY_COMPOSE_NETWORK:-day-ahead-forecast_default}"

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
  printf 'Starts the local stack and runs opt-in end-to-end availability tests in Docker.\n'
  printf 'Set ENERGY_AVAILABILITY_START_STACK=0 to test an already running stack.\n'
  printf 'Override AVAILABILITY_*_URL values only if the Docker test container needs custom endpoints.\n'
  exit 0
fi

if [ "$START_STACK" != "0" ]; then
  ./run-server.sh
fi

mkdir -p "$MAVEN_REPOSITORY"

docker run --rm \
  --network "$COMPOSE_NETWORK" \
  --user "$(id -u):$(id -g)" \
  --volume "$SCRIPT_DIR/quarkus:/workspace" \
  --volume "$MAVEN_REPOSITORY:/maven-repository" \
  --workdir /workspace \
  "$MAVEN_IMAGE" \
  mvn \
  -Dmaven.repo.local=/maven-repository \
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
