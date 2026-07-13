#!/usr/bin/env sh
set -eu
docker compose down
docker compose up -d
