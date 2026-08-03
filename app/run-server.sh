#!/usr/bin/env sh
set -eu

: "${INFLUXDB_TOKEN:?export INFLUXDB_TOKEN before running this script}"

docker compose up -d --build

echo 'Backend: http://localhost:8080\n'
echo 'Grafana: http://localhost:3000\n'
