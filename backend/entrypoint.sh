#!/bin/bash
set -e
echo "=== QueryPilot Startup ==="
echo "[1/2] Indexing schemas..."
python scripts/startup_index.py
echo "[2/2] Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
