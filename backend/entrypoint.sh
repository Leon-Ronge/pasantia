#!/bin/sh
# Arranque del backend: migraciones, configuración inicial y servidor.
set -e

echo "Aplicando migraciones..."
python manage.py migrate --noinput

echo "Asegurando registro de Settings..."
python manage.py bootstrap_settings

echo "Recolectando archivos estáticos..."
python manage.py collectstatic --noinput

echo "Iniciando Gunicorn en 0.0.0.0:8000..."
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --access-logfile - \
  --error-logfile -
