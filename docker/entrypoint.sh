#!/bin/sh
set -e

mkdir -p /app/var/db /app/var/snapshots /vaults
python manage.py migrate --noinput

exec "$@"
