#!/usr/bin/env bash
# One-command local run (in-memory bus, SQLite). Usage: bash scripts/run_all.sh
set -e
cd "$(dirname "$0")/.."
[ -f artifacts/current.json ] || python -m app.models.train --n 20000
python -m app.main
