#!/usr/bin/env bash
# Single entry point for the test suite. Runs with no radio hardware attached.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m pytest -q tests/ "$@"
