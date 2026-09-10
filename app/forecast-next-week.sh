#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

docker compose --profile forecasts run --rm forecast-runner \
  --base-url http://forecast-backend:8080 \
  --target all \
  --forecast-days 7 \
  "$@"
