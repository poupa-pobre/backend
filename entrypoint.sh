#!/bin/sh
# Entrypoint de produção: coleta estáticos, aplica migrações e sobe o gunicorn.
# Roda dentro do container `api` (ver docker-compose.prod.yml).
set -e

echo ">> collectstatic"
python manage.py collectstatic --noinput

echo ">> migrate"
python manage.py migrate --noinput

echo ">> gunicorn"
exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
