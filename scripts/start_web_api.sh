#!/usr/bin/env sh
set -eu

alembic upgrade head
exec uvicorn api.server:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
