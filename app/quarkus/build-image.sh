#!/usr/bin/env sh
set -eu

./mvnw -DskipTests package
docker build -t day-ahead-forecast-backend .
