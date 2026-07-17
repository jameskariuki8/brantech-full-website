# Dockerize the Brantech/Teklora site behind a Cloudflare Tunnel

**Date:** 2026-05-29
**Status:** Approved (design)

## Goal

Containerize the Django application and its PostgreSQL/pgvector database, and
expose the site through a Cloudflare Tunnel so that **no ports are bound or
published on the host**. The only outbound connection is `cloudflared` dialing
the Cloudflare edge over 443; inbound traffic arrives through the tunnel.

## Non-goals

- Nginx / dedicated static file server (explicitly deferred — see Tradeoffs).
- Kubernetes, multi-host orchestration, or CI/CD pipeline changes.
- Pinning the full existing `requirements.txt` (kept in current unpinned style).
- Auto-running `init_vector_stores` (it calls the paid Gemini API; manual only).

## Architecture / topology

Three services in a single `docker-compose.yml`. No `ports:` mappings are
published to the host — services talk over the default internal Docker network.

```
┌─────────────────────────────────────────────┐
│ docker network (internal only)               │
│                                               │
│  cloudflared ──tunnel──► web:8000             │
│   (TUNNEL_TOKEN)         (gunicorn+whitenoise)│
│                              │                │
│                              ▼                │
│                          db:5432              │
│                          (pgvector/pgvector)  │
└─────────────────────────────────────────────┘
        ▲
        └── outbound 443 to Cloudflare edge only
```

| Service       | Image / build                     | Role                                                                 |
|---------------|-----------------------------------|----------------------------------------------------------------------|
| `db`          | `pgvector/pgvector:pg16`          | Postgres with `vector` extension preinstalled. Healthcheck `pg_isready`. |
| `web`         | built from `./Dockerfile`         | Gunicorn serving `brandtechsolution.wsgi`; WhiteNoise serves static. Depends on `db` healthy. |
| `cloudflared` | `cloudflare/cloudflared:latest`   | `tunnel --no-autoupdate run --token ${TUNNEL_TOKEN}`. Depends on `web`. |

Public-hostname → `http://web:8000` routing is configured in the Cloudflare
Zero Trust dashboard (token-based / remotely-managed tunnel). No tunnel config
files live in the repo.

## Persistence (bind mounts into the project)

All persistent state lives in an in-project `./data/` directory (bind mounts,
not Docker named volumes) so it is visible in the project tree:

- `./data/postgres` → `/var/lib/postgresql/data` (database files)
- `./data/media`    → container `MEDIA_ROOT` (user uploads: blog/project images)

`./data/` is added to `.gitignore`.

## Container build & startup

### `Dockerfile`
- Base `python:3.13-slim` (matches the `.pyc` cache markers showing 3.13).
- Install build/runtime deps for `psycopg2` and `pillow`:
  `libpq-dev`, `gcc`, `libjpeg-dev`, `zlib1g-dev` (plus runtime `libpq5`, `libjpeg`).
- `pip install --no-cache-dir -r requirements.txt`.
- Copy the project; `WORKDIR /app/brandtechsolution`.
- Create and run as a non-root user; ensure `MEDIA_ROOT` and `STATIC_ROOT`
  directories are writable by that user.

### `entrypoint.sh` (web service)
1. Wait for `db` to be reachable.
2. `python manage.py migrate --noinput`
3. `python manage.py collectstatic --noinput`
4. `exec gunicorn brandtechsolution.wsgi:application --bind 0.0.0.0:8000 --workers 3`

### `requirements.txt`
Add (unpinned, matching existing style):
- `gunicorn`
- `whitenoise`

## Settings changes (`brandtechsolution/settings.py`)

All edits are additive and preserve existing local/Windows behavior via defaults.

1. **Env-driven static/media roots.** Replace the brittle `os.name`-based
   selection of `STATIC_ROOT` / `MEDIA_ROOT` with values sourced from
   `config.py`, defaulting to `BASE_DIR / "staticfiles"` and `BASE_DIR / "media"`.
   The container overrides them via env. New settings in `config.py`:
   `static_root: str` and `media_root: str` (with the above defaults).
2. **WhiteNoise.** Insert `whitenoise.middleware.WhiteNoiseMiddleware`
   immediately after `SecurityMiddleware`; set
   `STORAGES["staticfiles"]["BACKEND"]` to
   `whitenoise.storage.CompressedManifestStaticFilesStorage`.
3. **Media serving.** WhiteNoise serves only static files, not user uploads.
   Add a permanent media route (not gated on `DEBUG`) in
   `brandtechsolution/urls.py` using `django.views.static.serve` over
   `MEDIA_URL` so uploaded images are served by Django/gunicorn.

`ALLOWED_HOSTS`, `SECRET_KEY`, `DEBUG`, DB credentials, `GOOGLE_API_KEY`, and
`TUNNEL_TOKEN` all come from `.env` via compose `env_file:`. In the container,
`DATABASE_HOST=db`.

## Config files & secrets

- **`.env`** (already gitignored) holds all secrets including `TUNNEL_TOKEN`.
- **`env.example`** extended with Docker-relevant vars: `DATABASE_HOST=db`,
  `TUNNEL_TOKEN=`, `STATIC_ROOT=`, `MEDIA_ROOT=`, and `DEBUG=False` guidance.
- **`.dockerignore`** excludes: `.venv`, `__pycache__`, `.git`, `data/`,
  `media/`, `staticfiles/`, `static/`, `*.sqlite3`, `docs/`, `.vscode`, `.cursor`.
- **`.gitignore`** gains `/data/`.

## Tradeoffs / known limitations

- **Media via Django.** Serving user uploads through gunicorn is acceptable for
  a low-traffic portfolio site. If media traffic grows, the cue is to adopt the
  previously-considered Nginx + shared-volume option.
- **`latest` tag for cloudflared.** Convenience over reproducibility; can be
  pinned later.
- **Bind-mounted Postgres data** is Linux-host oriented (the target deploy
  environment); fine for this project.

## Verification plan

Full end-to-end requires the operator's real `TUNNEL_TOKEN` and `GOOGLE_API_KEY`.
Without those we can still verify:
1. `docker compose build` succeeds.
2. `docker compose up db web` brings `db` to healthy and `web` runs entrypoint
   (migrate + collectstatic succeed).
3. Internal HTTP check: `docker compose exec web curl -sf http://localhost:8000/`
   (or a one-off container) returns the homepage.
4. `cloudflared` starts and registers the tunnel once a real token is supplied
   (operator-verified against the live hostname).

## Out-of-scope follow-ups (documented, not built)

- Manual one-off after first deploy: `docker compose exec web python manage.py init_vector_stores`.
- Manual superuser creation: `docker compose exec web python manage.py createsuperuser`.
