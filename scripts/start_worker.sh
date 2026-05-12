#!/bin/sh
set -e

echo "Starting worker..."
exec python -m invoice_parser.worker.main
