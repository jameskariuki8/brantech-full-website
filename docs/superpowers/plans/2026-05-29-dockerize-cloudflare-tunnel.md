# Dockerize + Cloudflare Tunnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Django site, its pgvector Postgres DB, and a Cloudflare Tunnel as Docker containers with no host ports published, persisting DB + media to an in-project `./data/` directory.

**Architecture:** Single `docker-compose.yml` with three services — `db` (pgvector/pgvector), `web` (gunicorn + WhiteNoise serving Django), and `cloudflared` (token-based tunnel → `web:8000`). No `ports:` are published; `cloudflared` dials the Cloudflare edge outbound and proxies inbound traffic to `web` over the internal Docker network.

**Tech Stack:** Docker, docker compose v2, Python 3.13-slim, gunicorn, WhiteNoise, Postgres 16 + pgvector, cloudflared.

---

## Environment / secrets model (read before starting)

Two distinct env situations — do not conflate them:

- **Local (non-Docker) dev:** `brandtechsolution/.env`, read by `config.py` (`env_file = BASE_DIR/".env"`). **Unchanged** by this work.
- **Docker:** a `.env` file at the **repo root** (next to `docker-compose.yml`).
  - Compose auto-reads root `.env` for `${VAR}` interpolation inside the compose file.
  - Compose `env_file: .env` injects those vars as real environment variables into the containers.
  - `pydantic-settings` (`config.py`) reads real environment variables from `os.environ`, which take precedence over (and do not require) a physical `.env` file inside the container. So the app is configured correctly in Docker even though `/app/brandtechsolution/.env` does not exist.

Both `.env` files are already covered by `.gitignore` (`.env` pattern).

## File structure

| Path | Create/Modify | Responsibility |
|------|---------------|----------------|
| `brandtechsolution/requirements.txt` | Modify | Add `gunicorn`, `whitenoise`. |
| `brandtechsolution/brandtechsolution/config.py` | Modify | Add env-driven `static_root` / `media_root`. |
| `brandtechsolution/brandtechsolution/settings.py` | Modify | Use config roots; add WhiteNoise middleware + `STORAGES`. |
| `brandtechsolution/brandtechsolution/urls.py` | Modify | Always-on media serving route. |
| `Dockerfile` | Create | Build the `web` image. |
| `entrypoint.sh` | Create | migrate → collectstatic → exec gunicorn. |
| `docker-compose.yml` | Create | The three services. |
| `.dockerignore` | Create | Keep build context lean. |
| `.gitignore` | Modify | Ignore `/data/`. |
| `brandtechsolution/env.example` | Modify | Document Docker vars. |
| `README.md` | Modify | Docker + tunnel run instructions. |

---

### Task 1: Add gunicorn + whitenoise to requirements

**Files:**
- Modify: `brandtechsolution/requirements.txt`

- [ ] **Step 1: Append the two packages** (keep existing unpinned style)

The file becomes:

```
django
djangorestframework
pillow
langchain
langgraph
langchain-community
langchain-google-genai
langchain-text-splitters
pydantic-settings
psycopg2-binary
pgvector
gunicorn
whitenoise
```

- [ ] **Step 2: Verify the additions**

Run: `tail -2 brandtechsolution/requirements.txt`
Expected: prints `gunicorn` and `whitenoise`.

- [ ] **Step 3: Commit**

```bash
git add brandtechsolution/requirements.txt
git commit -m "build: add gunicorn and whitenoise dependencies"
```

---

### Task 2: Make static/media roots env-driven in config.py

**Files:**
- Modify: `brandtechsolution/brandtechsolution/config.py`

- [ ] **Step 1: Add two settings** to `AppSettings`, after the Database block (after the `database_conn_max_age` line, before the closing of the class)

```python
    # ============================================================
    # Static & Media (filesystem paths)
    # ============================================================
    static_root: str = str(BASE_DIR / "staticfiles")
    media_root: str = str(BASE_DIR / "media")
```

Note: `BASE_DIR` is already defined at the top of `config.py` as `Path(__file__).resolve().parent.parent` (the `brandtechsolution/` directory).

- [ ] **Step 2: Verify config still loads** (uses local `brandtechsolution/.env`)

Run: `cd brandtechsolution && python -c "from brandtechsolution.config import config; print(config.static_root, config.media_root)"`
Expected: prints two absolute paths ending in `/staticfiles` and `/media` (no traceback).

- [ ] **Step 3: Commit**

```bash
git add brandtechsolution/brandtechsolution/config.py
git commit -m "config: add env-driven static_root and media_root"
```

---

### Task 3: Wire static/media roots + WhiteNoise into settings.py

**Files:**
- Modify: `brandtechsolution/brandtechsolution/settings.py`

- [ ] **Step 1: Add WhiteNoise middleware** — insert it immediately after `SecurityMiddleware`. Replace:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
```

with:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
```

- [ ] **Step 2: Replace the `os.name`-based static/media block.** Replace these lines (currently ~140-156):

```python
STATIC_URL = '/static/'

# Local environment
LOCAL_STATIC_ROOT = BASE_DIR / "staticfiles"
LOCAL_MEDIA_ROOT = BASE_DIR / "media"

# EC2 production paths
PRODUCTION_STATIC_ROOT = "/var/www/brandtech/static"
PRODUCTION_MEDIA_ROOT = "/var/www/brandtech/media"

STATICFILES_DIRS = [
    BASE_DIR / 'brand' / 'static',
]

STATIC_ROOT = PRODUCTION_STATIC_ROOT if os.name != 'nt' else LOCAL_STATIC_ROOT
MEDIA_ROOT = PRODUCTION_MEDIA_ROOT if os.name != 'nt' else LOCAL_MEDIA_ROOT
MEDIA_URL = '/media/'
```

with:

```python
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / 'brand' / 'static',
]

# Roots come from config (env-driven); see brandtechsolution/config.py
STATIC_ROOT = config.static_root
MEDIA_ROOT = config.media_root
MEDIA_URL = '/media/'

# WhiteNoise compressed + manifest storage for collected static files
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

- [ ] **Step 3: Verify Django check passes**

Run: `cd brandtechsolution && python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 4: Verify collectstatic succeeds with manifest storage** (this is the real risk — manifest storage hard-fails on a missing referenced asset)

Run: `cd brandtechsolution && python manage.py collectstatic --noinput`
Expected: `N static files copied ... post-processed`. No `ValueError: Missing staticfiles manifest entry`.

**Contingency:** if collectstatic fails with a "Missing staticfiles manifest entry" / unresolvable `url(...)` error from a CSS file, change the staticfiles backend in Step 2 from `CompressedManifestStaticFilesStorage` to `CompressedStaticFilesStorage` (compression without the strict manifest) and re-run. Record which one you used.

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/brandtechsolution/settings.py
git commit -m "settings: use env-driven static/media roots and enable WhiteNoise"
```

---

### Task 4: Always-on media serving route

**Files:**
- Modify: `brandtechsolution/brandtechsolution/urls.py`

WhiteNoise serves only static files, not user uploads, so media must be served by Django (acceptable for this low-traffic site).

- [ ] **Step 1: Replace the file contents** with:

```python
from django.contrib import admin
from django.urls import path, include, re_path
from brand import views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('brand.urls')),
    path('appointments/', include('appointments.urls')),
    path('api/', include('brand.api_urls')),
    path('api/ai/', include('ai_workflows.urls')),
    path('accounts/login/', views.login_view),
    path('accounts/logout/', views.logout_view),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production (DEBUG=False) WhiteNoise serves static but not user media,
    # so serve uploaded media files through Django.
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
```

- [ ] **Step 2: Verify URLconf imports cleanly**

Run: `cd brandtechsolution && python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Commit**

```bash
git add brandtechsolution/brandtechsolution/urls.py
git commit -m "urls: serve user media through Django when DEBUG is off"
```

---

### Task 5: Create the entrypoint script

**Files:**
- Create: `entrypoint.sh` (repo root)

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /app/brandtechsolution

echo "[entrypoint] Applying database migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting gunicorn..."
exec gunicorn brandtechsolution.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --access-logfile - \
    --error-logfile -
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x entrypoint.sh && head -1 entrypoint.sh`
Expected: prints `#!/usr/bin/env bash`.

- [ ] **Step 3: Commit**

```bash
git add entrypoint.sh
git commit -m "docker: add web entrypoint (migrate, collectstatic, gunicorn)"
```

---

### Task 6: Create the Dockerfile

**Files:**
- Create: `Dockerfile` (repo root)

Note: `psycopg2-binary` and `pillow` ship manylinux wheels, so no system build packages are needed for a normal build. The container runs as root for simplicity so that the bind-mounted `./data/media` directory is writable regardless of host UID (acceptable for this single-tenant, tunnel-only deployment).

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY brandtechsolution/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application code
COPY brandtechsolution/ ./brandtechsolution/
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

WORKDIR /app/brandtechsolution

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
```

- [ ] **Step 2: Verify the image builds** (no DB/secrets needed for build)

Run: `docker build -t brantech-web .`
Expected: build completes with `naming to docker.io/library/brantech-web` (or `Successfully tagged`). If pip fails building a package from source, add a build-deps layer before `pip install`:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "docker: add web image Dockerfile"
```

---

### Task 7: Create .dockerignore

**Files:**
- Create: `.dockerignore` (repo root)

- [ ] **Step 1: Write it**

```
.git
.gitignore
.venv
venv
**/__pycache__
**/*.pyc
data
brandtechsolution/media
brandtechsolution/staticfiles
brandtechsolution/static
**/*.sqlite3
docs
.vscode
.cursor
*.md
PERFORMANCE_*.md
SECURITY_SUMMARY.md
```

- [ ] **Step 2: Verify it exists**

Run: `cat .dockerignore | head -3`
Expected: prints `.git`, `.gitignore`, `.venv`.

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "docker: add .dockerignore"
```

---

### Task 8: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml` (repo root)

`${VAR}` values are interpolated by compose from the root `.env` (Task 10). No `ports:` are published anywhere.

- [ ] **Step 1: Write the compose file**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DATABASE_NAME}
      POSTGRES_USER: ${DATABASE_USER}
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD}
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DATABASE_USER} -d ${DATABASE_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 10

  web:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_HOST: db
    volumes:
      - ./data/media:/app/brandtechsolution/media
    depends_on:
      db:
        condition: service_healthy

  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run --token ${TUNNEL_TOKEN}
    depends_on:
      - web
```

- [ ] **Step 2: Validate compose syntax** (needs a root `.env`; if Task 10 not done yet, create a throwaway one first)

Run: `docker compose config >/dev/null && echo OK`
Expected: `OK` (warnings about an empty `TUNNEL_TOKEN` are fine at this stage).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "docker: add compose with db, web, cloudflared (no published ports)"
```

---

### Task 9: Ignore the data directory

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append a data-directory rule.** Add under the "Project specific" section:

```
# Docker persistent data (bind mounts)
/data/
```

- [ ] **Step 2: Verify it is ignored**

Run: `mkdir -p data/postgres && git check-ignore data/postgres`
Expected: prints `data/postgres`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore Docker /data directory"
```

---

### Task 10: Document Docker env vars + write the root .env

**Files:**
- Modify: `brandtechsolution/env.example`
- Create: `.env` (repo root, NOT committed — gitignored)

- [ ] **Step 1: Append a Docker section to `brandtechsolution/env.example`**

```
# ============================================================
# Docker / Cloudflare Tunnel (used by docker-compose at repo root)
# ============================================================
# When running via Docker, place a copy of this file as `.env` at the REPO ROOT
# (next to docker-compose.yml). Compose injects these as real env vars, which
# pydantic-settings reads directly — no in-container .env file is required.

# In Docker the app talks to the bundled Postgres service by name:
# DATABASE_HOST=db

# Set DEBUG=False for production behind the tunnel:
# DEBUG=False

# Static/media filesystem roots inside the container (defaults are fine):
# STATIC_ROOT=/app/brandtechsolution/staticfiles
# MEDIA_ROOT=/app/brandtechsolution/media

# Cloudflare Tunnel token (create a tunnel in the Zero Trust dashboard,
# add a public hostname routing to http://web:8000, and paste its token here):
TUNNEL_TOKEN=your-cloudflare-tunnel-token-here
```

- [ ] **Step 2: Create the real root `.env` for Docker.** Copy the example and fill real values. The minimum required keys for the stack to boot:

```
SECRET_KEY=<real-secret>
DEBUG=False
ALLOWED_HOSTS=["your-domain.com","www.your-domain.com"]
GOOGLE_API_KEY=<real-key>
DATABASE_ENGINE=postgresql
DATABASE_NAME=brantech
DATABASE_USER=<db-user>
DATABASE_PASSWORD=<db-password>
DATABASE_HOST=db
DATABASE_PORT=5432
TUNNEL_TOKEN=<real-tunnel-token>
```

- [ ] **Step 3: Verify .env is gitignored**

Run: `git check-ignore .env`
Expected: prints `.env`.

- [ ] **Step 4: Commit (env.example only — never the real .env)**

```bash
git add brandtechsolution/env.example
git commit -m "docs: document Docker/Cloudflare env vars in env.example"
```

---

### Task 11: End-to-end bring-up verification (db + web)

This verifies everything except the live tunnel (which needs the operator's real `TUNNEL_TOKEN` + DNS). Requires a real `GOOGLE_API_KEY` and DB creds in the root `.env`.

- [ ] **Step 1: Start db + web only**

Run: `docker compose up -d --build db web`
Expected: both containers start; `docker compose ps` shows `db` healthy and `web` running.

- [ ] **Step 2: Confirm entrypoint ran migrations + collectstatic**

Run: `docker compose logs web | grep -E "migrations|static|gunicorn"`
Expected: lines showing migrations applied, static collected, and gunicorn listening on `0.0.0.0:8000`.

- [ ] **Step 3: Hit the app on the internal network**

Run: `docker compose exec web curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/`
Expected: `200`.

- [ ] **Step 4: Confirm media bind mount is writable**

Run: `docker compose exec web sh -c 'touch /app/brandtechsolution/media/.write_test && ls -la /app/brandtechsolution/media/.write_test' && ls data/media/.write_test`
Expected: the file shows up both inside the container and on the host at `data/media/.write_test`. Clean up: `docker compose exec web rm /app/brandtechsolution/media/.write_test`.

- [ ] **Step 5: Tear down**

Run: `docker compose down`
Expected: containers removed; `data/postgres` and `data/media` remain on the host.

- [ ] **Step 6: (operator, manual) Bring up the full stack with the tunnel**

Run: `docker compose up -d --build`
Expected: `cloudflared` logs show `Registered tunnel connection` and the configured public hostname serves the site over HTTPS. (Requires a valid `TUNNEL_TOKEN` and a dashboard public-hostname route → `http://web:8000`.)

---

### Task 12: Document Docker usage in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Running with Docker (Cloudflare Tunnel)" section** near the end of `README.md`:

```markdown
## 🐳 Running with Docker (behind Cloudflare Tunnel)

The stack runs three containers — `db` (Postgres + pgvector), `web`
(gunicorn + WhiteNoise), and `cloudflared` (Cloudflare Tunnel) — with **no host
ports published**. Inbound traffic arrives only through the tunnel.

### 1. Configure environment

Create a `.env` file at the **repo root** (next to `docker-compose.yml`) based on
`brandtechsolution/env.example`. For Docker, set `DATABASE_HOST=db`, `DEBUG=False`,
and a real `TUNNEL_TOKEN`.

### 2. Create the Cloudflare Tunnel

In the Cloudflare Zero Trust dashboard → Networks → Tunnels, create a tunnel,
add a **public hostname** routing your domain to `http://web:8000`, and copy the
tunnel **token** into `TUNNEL_TOKEN` in `.env`.

### 3. Build and run

```bash
docker compose up -d --build
```

Persistent data lives in `./data/` (`./data/postgres`, `./data/media`).

### 4. One-off management commands

```bash
# Create an admin user
docker compose exec web python manage.py createsuperuser

# Build vector embeddings for blog posts/projects (uses the Gemini API)
docker compose exec web python manage.py init_vector_stores
```
```

- [ ] **Step 2: Verify the section renders** (sanity check the heading exists)

Run: `grep -n "Running with Docker" README.md`
Expected: prints the heading line.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add Docker + Cloudflare Tunnel run instructions"
```

---

## Self-review notes

- **Spec coverage:** topology (Tasks 6–8), containerized pgvector (Task 8), gunicorn+WhiteNoise (Tasks 1,3,5), token tunnel (Tasks 8,10,12), bind-mount persistence to `./data/` (Tasks 8,9), env-driven static/media roots (Tasks 2,3), media via Django (Task 4), env vars + `.dockerignore` (Tasks 7,10), verification (Task 11), manual one-offs documented (Task 12). All spec sections map to tasks.
- **Deviations from spec, by design:** (1) `web` runs as root rather than non-root, to avoid host/container UID friction on the bind-mounted media dir — noted in Task 6. (2) Dockerfile installs no apt build deps by default (wheels suffice) with an explicit contingency layer — noted in Task 6. (3) Manifest static storage has a documented fallback to non-manifest in Task 3 Step 4. These were judgment calls to make the first deploy robust; flag to the user if any are unwanted.
- **No placeholders:** every code/edit step contains full content; commands have expected output.
