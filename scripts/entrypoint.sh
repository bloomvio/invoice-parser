#!/bin/sh
set -e

if [ "$SERVICE" = "worker" ]; then
  echo "Starting worker..."
  exec python -m invoice_parser.worker.main
else
  echo "Running migrations..."
  PYTHONPATH=src python -m alembic upgrade head
  echo "Starting API..."
  exec uvicorn invoice_parser.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
fi
