#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Running Quarkus tests"
(cd "$ROOT_DIR/quarkus" && ./mvnw test)

echo "Running Python tests"
(cd "$ROOT_DIR/python" && .venv/bin/python -m unittest discover -s tests -p "test_*.py")
