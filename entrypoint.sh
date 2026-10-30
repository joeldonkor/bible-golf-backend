#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py seed_content

exec gunicorn config.asgi:application \
  --worker-class uvicorn_worker.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --timeout 0 \
  --graceful-timeout 30 \
  --max-requests 10000 \
  --max-requests-jitter 1000 \
  --access-logfile - \
  --error-logfile -
