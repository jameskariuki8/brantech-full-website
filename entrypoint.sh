#!/usr/bin/env bash
set -euo pipefail

cd /app/brandtechsolution

# The image serves four roles (web, worker, beat, and one-off commands), so the
# entrypoint dispatches on its first argument instead of hardcoding gunicorn.
# Only the web role migrates and collects static: running migrate from three
# containers at once races, and the worker has no static files to serve.
ROLE="${1:-web}"

case "$ROLE" in
  web)
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --noinput

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --noinput

    echo "[entrypoint] Starting gunicorn..."
    exec gunicorn brandtechsolution.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
    ;;

  worker)
    # Prefork, not gevent: the tasks are I/O-bound on the Gemini API, but the
    # stack underneath them (psycopg2, LangChain) does not monkey-patch
    # cleanly, and silent connection corruption is a far worse failure than
    # a couple of idle worker slots.
    echo "[entrypoint] Starting celery worker..."
    exec celery -A brandtechsolution worker \
        --loglevel=info \
        --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
    ;;

  beat)
    # --schedule under /tmp: the default writes celerybeat-schedule into the
    # working directory, which is read-only in some deployments and would
    # otherwise be shared between replicas.
    echo "[entrypoint] Starting celery beat..."
    exec celery -A brandtechsolution beat \
        --loglevel=info \
        --schedule=/tmp/celerybeat-schedule
    ;;

  *)
    # Anything else is a one-off: `docker compose run --rm web python manage.py shell`
    exec "$@"
    ;;
esac
