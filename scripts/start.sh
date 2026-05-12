#!/bin/sh
set -e

echo "Running database migrations..."
PYTHONPATH=src python -m alembic upgrade head

echo "Starting server..."
exec uvicorn invoice_parser.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
