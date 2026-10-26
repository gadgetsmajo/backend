#!/usr/bin/env bash
set -e

python manage.py migrate --noinput

if [ -n "${ADMIN_PASSWORD:-}" ]; then
    ADMIN_EMAIL="${ADMIN_EMAIL:-majogadgets@admin.com}" \
    ADMIN_NAME="${ADMIN_NAME:-Majo Gadgets}" \
        python manage.py create_admin
fi

python manage.py seed_districts
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:?PORT must be set}"
