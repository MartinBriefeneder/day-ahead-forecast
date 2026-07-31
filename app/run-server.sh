#!/usr/bin/env sh
set -eu

INFLUX_TOKEN_FILE="./influxdb/admin-token.json"

if [ ! -f "$INFLUX_TOKEN_FILE" ]; then
  printf 'Missing InfluxDB token file: %s\n' "$INFLUX_TOKEN_FILE" >&2
  exit 1
fi

INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$INFLUX_TOKEN_FILE")
export INFLUXDB_TOKEN

if [ -z "$INFLUXDB_TOKEN" ]; then
  printf 'Could not read token from %s\n' "$INFLUX_TOKEN_FILE" >&2
  exit 1
fi

printf 'Packaging Quarkus backend...\n'
cd ./quarkus
./mvnw -DskipTests package
cd ..

printf 'Starting InfluxDB, Grafana, and containerized Quarkus backend...\n'
docker compose -f docker-compose.yaml -f docker-compose.backend.yaml up -d --build influxdb grafana backend

printf 'Backend: http://localhost:8080\n'
printf 'Grafana: http://localhost:3000\n'
