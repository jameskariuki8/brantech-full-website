# Brantech Solution Fullstack Project

This repository contains the Django web application for **Brantech Solution** — a dynamic and scalable platform for web development and digital innovation projects.

## 🚀 Features

- **Portfolio Website**: Showcase services, projects, and company information
- **Blog System**: Content management for blog posts with categories, tags, and featured posts
- **Appointment Booking**: Full appointment management system with availability checking
- **AI Chatbot**: Intelligent chatbot powered by Google Gemini with RAG (Retrieval-Augmented Generation) capabilities
- **Admin Panel**: Comprehensive admin interface for managing content
- **Staff Roles & Permissions**: Capability-based access control for the admin panel, with email invitations and an append-only audit log
- **REST API**: Full API endpoints for blog posts and projects

## 🛠️ Project Setup Guide

### Prerequisites

- Python 3.8+
- PostgreSQL (optional, SQLite is used by default)
- Virtual environment (recommended)

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/jameskariuki8/brantech-full-website.git
cd brantech-full-website/brandtechsolution
```

### 2️⃣ Create and Activate Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

### 4️⃣ Environment Configuration

Copy the example environment file and configure it:

```bash
cp env.example .env
```

Edit `.env` file with your configuration:

```bash
# Required settings
SECRET_KEY=your-secret-key-here
GOOGLE_API_KEY=your-google-api-key-here
DATABASE_USER=your-db-user
DATABASE_PASSWORD=your-db-password

# Optional settings
DEBUG=True
ALLOWED_HOSTS=["127.0.0.1","localhost"]
```

**Note**: Generate a new SECRET_KEY for production:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5️⃣ Database Setup

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 6️⃣ Initialize Vector Stores (for AI Chatbot)

The AI chatbot uses vector embeddings for blog posts and projects. Initialize the vector stores:

```bash
python manage.py init_vector_stores
```

This command creates vector embeddings for all existing blog posts and projects in the database.

### 7️⃣ Run the Development Server

```bash
python manage.py runserver
```

Visit: **http://127.0.0.1:8000/**

## 📁 Project Structure

```
brandtechsolution/
├── brand/              # Main website app (home, blog, projects, etc.)
├── appointments/       # Appointment booking system
├── ai_workflows/       # AI chatbot with LangChain/Gemini integration
├── staff/              # Capabilities, roles, invitations and the audit log
├── brandtechsolution/  # Django project settings
├── media/              # User-uploaded files (images, etc.)
├── staticfiles/        # Collected static files
├── chroma_db/          # Vector database for RAG
└── manage.py           # Django management script
```

## 🔌 API Endpoints

### Blog Posts API

- `GET /api/posts/` - List all blog posts
- `POST /api/posts/` - Create a new blog post (authenticated)
- `GET /api/posts/<id>/` - Get a specific blog post
- `POST /api/posts/<id>/` - Update a blog post (authenticated)
- `DELETE /api/posts/<id>/` - Delete a blog post (authenticated)

### Projects API

- `GET /api/projects/` - List all projects
- `POST /api/projects/` - Create a new project (authenticated)
- `GET /api/projects/<id>/` - Get a specific project
- `POST /api/projects/<id>/` - Update a project (authenticated)
- `DELETE /api/projects/<id>/` - Delete a project (authenticated)

### AI Chatbot API

- `POST /api/ai/chat/` - Chat endpoint (authenticated)
- `POST /api/ai/chat/` - Chat endpoint (public, uses session)
- `GET /api/ai/chat/history/` - Get conversation history
- `POST /api/ai/chat/clear/` - Clear conversation history

### Appointments API

- `GET /appointments/` - List appointments (staff only)
- `POST /appointments/create/` - Create a new appointment
- `POST /appointments/check-availability/` - Check time slot availability
- `GET /appointments/get/` - Get appointment details
- `GET /appointments/admin/manage/<id>/` - Admin appointment management

### Staff & Roles API

All of these require the `manage_staff` capability (see
[Staff roles and permissions](#staff-roles-and-permissions)).

- `GET /api/staff/capabilities/` - The capability registry, grouped as the UI shows it
- `GET|POST /api/staff/roles/` - List and create roles
- `GET|PUT|PATCH|DELETE /api/staff/roles/<id>/` - Read, edit and delete a role
- `GET /api/staff/people/` - List staff accounts
- `GET|PUT|PATCH /api/staff/people/<id>/` - Read and edit one account's roles and active state
- `GET|POST /api/staff/invitations/` - List pending invitations and issue a new one
- `POST /api/staff/invitations/<id>/resend/` - Send a fresh link
- `DELETE /api/staff/invitations/<id>/` - Revoke an invitation
- `GET /api/staff/activity/` - The audit log (read-only)

Accepting an invitation happens outside the API, at
`GET|POST /staff/invite/<token>/`, which is public by design — the invitee has
no account yet.

## 🧪 Running Tests

```bash
# Run all tests
python manage.py test

# Run tests for a specific app
python manage.py test brand
python manage.py test appointments
python manage.py test ai_workflows
```

## 🚀 Deployment

### Production Checklist

1. Set `DEBUG=False` in `.env`
2. Set a strong `SECRET_KEY`
3. Configure `ALLOWED_HOSTS` with your domain
4. Set up PostgreSQL database
5. Configure email settings for production
6. Collect static files: `python manage.py collectstatic`
7. Set up proper media file serving
8. Configure environment variables on your server

### Upgrading an existing deployment: staff roles

This release adds migrations for the new `staff` app and a `status` field on
`BlogPost`. Run `python manage.py migrate` on deploy. The blog migration
backfills every existing post to `published`, so nothing disappears from the
public site. No new Python dependencies are added, so a plain container
restart is sufficient once migrations have run. (Under Docker Compose the
`web` entrypoint already runs `migrate` for you.)

The staff migration also creates the four preset roles. See
[Staff roles and permissions](#staff-roles-and-permissions) for what they
grant and how to invite people.

### Environment Variables for Production

```bash
DEBUG=False
SECRET_KEY=your-production-secret-key
ALLOWED_HOSTS=["yourdomain.com","www.yourdomain.com"]
DATABASE_ENGINE=postgresql
DATABASE_NAME=brantech
DATABASE_USER=your-db-user
DATABASE_PASSWORD=your-db-password
DATABASE_HOST=localhost
DATABASE_PORT=5432
GOOGLE_API_KEY=your-google-api-key
```

## 📚 Documentation

- [AI Workflows README](brandtechsolution/ai_workflows/README.md) - Detailed documentation for the AI chatbot integration
- [LangChain Integration Docs](docs/langchain-quick-start-guide.md) - Quick start guide for LangChain

## 🛠️ Technology Stack

- **Backend**: Django 5.2.7
- **Database**: PostgreSQL / SQLite
- **AI/ML**: LangChain, LangGraph, Google Gemini
- **Vector Store**: ChromaDB
- **Frontend**: HTML, CSS, JavaScript
- **API**: Django REST Framework

## 🐳 Running with Docker (behind Cloudflare Tunnel)

The stack runs three containers — `db` (Postgres + pgvector), `web`
(gunicorn + WhiteNoise), and `cloudflared` (Cloudflare Tunnel) — with **no host
ports published**. Inbound traffic arrives only through the tunnel; `cloudflared`
dials the Cloudflare edge outbound and proxies to `web` over the internal network.

Persistent data lives in the in-project `./data/` directory (`./data/postgres`,
`./data/media`), which is gitignored.

### 1. Configure environment

Two gitignored files at the **repo root** (next to `docker-compose.yml`):

- **`.env`** — app + database config, based on `brandtechsolution/env.example`.
  For Docker, set `DATABASE_HOST=db` and `DEBUG=False`, and set `ALLOWED_HOSTS`
  and `CSRF_TRUSTED_ORIGINS` to your real domain — `CSRF_TRUSTED_ORIGINS` (with
  the `https://` scheme) is **required** behind the tunnel or form/admin POSTs
  return HTTP 403. Compose injects these as real environment variables
  (pydantic-settings reads them directly — no in-container `.env` file is
  required or baked into the image).
- **`cloudflared.env`** — contains only the tunnel token, kept separate so it
  never enters the web container's environment or the process command line:

  ```
  TUNNEL_TOKEN=your-cloudflare-tunnel-token-here
  ```

### 2. Create the Cloudflare Tunnel

In the Cloudflare Zero Trust dashboard → Networks → Tunnels, create a tunnel,
add a **public hostname** routing your domain to `http://web:8000`, and copy the
tunnel **token** into `cloudflared.env`.

### 3. Build and run

```bash
docker compose up -d --build
```

The `web` entrypoint runs `migrate` and `collectstatic` automatically, then
starts gunicorn.

> **First run / changing DB credentials:** Postgres initializes its data
> directory only once. If `./data/postgres` already exists, it ignores new
> credentials in `.env`. To start fresh, stop the stack and remove the directory
> (`docker run --rm -v "$(pwd)/data:/data" alpine rm -rf /data/postgres`).

### 4. One-off management commands

```bash
# Create an admin user
docker compose exec web python manage.py createsuperuser

# Build vector embeddings for blog posts/projects (uses the Gemini API)
docker compose exec web python manage.py init_vector_stores
```

### Notes

- Static files are served by WhiteNoise; user-uploaded media is served by Django
  (`CompressedStaticFilesStorage` is used rather than the strict manifest variant
  because some bundled CSS references a missing asset).
- The `web` container runs as root to keep the bind-mounted `./data/media`
  writable regardless of host UID.

## Bulk email outbox

Queued campaigns are sent by the `process_email_outbox` management command.

**Docker Compose deployments:** the `outbox` service in `docker-compose.yml`
runs this command automatically in a loop (every 60 seconds) alongside `web`
and `db`. There is nothing extra to configure or run — `docker compose up`
starts it for you.

**Non-Docker deployments:** run the command every minute via cron, using the
`python` interpreter that this project's dependencies are actually installed
into (e.g. the output of `which python` inside your project's virtualenv —
do NOT hard-code a path from a different environment's virtualenv layout;
there is no virtualenv inside the Docker image, so any such path is wrong
there):

    * * * * * cd /path/to/brandtechsolution && /path/to/your/python manage.py process_email_outbox --verbosity 0 >/dev/null 2>>/var/log/outbox-errors.log

Application DEBUG logging can include credential values, so avoid redirecting full stdout into a persistent log.

Tune `OUTBOX_BATCH_SIZE` (default 50) and cron frequency to stay under your
Gmail limits (~500/day free, ~2000/day Workspace). Example: batch 20 + a
per-5-minute cron ≈ safe for a free Gmail account.

`OUTBOX_STALE_CLAIM_MINUTES` controls how long a claimed-but-unfinished batch
is held before the reaper releases it back to the queue. A single run's
worst-case duration is bounded by `OUTBOX_BATCH_SIZE × EMAIL_TIMEOUT`
seconds, and this must stay below `OUTBOX_STALE_CLAIM_MINUTES × 60` — this
invariant is enforced by an automated test, so raising the batch size or
timeout requires raising `OUTBOX_STALE_CLAIM_MINUTES` to match.

### Managing campaign recipients

Every campaign card has a **View recipients (N)** button that opens the
recipient list. From there you can search by email or name, add an address
by hand, and remove individual addresses.

What removal does depends on how far the campaign has got:

| Campaign status | Removing a recipient |
|---|---|
| `draft` | Deletes the row and gives the slot back (`total` decreases) |
| `queued` / `sending` / `paused` | Marks the row `skipped`; it is never emailed, and `total` is left alone so the send record stays coherent |
| `sent` / `failed` | Refused — the campaign is finished and its history is immutable |

An address that has already been sent, failed, or is in flight is never
withdrawn, whatever the campaign's status.

**A removal persists across a rebuild.** Removing a recipient records a
durable, per-campaign exclusion for that address, independent of the
recipient row itself (which may be deleted, in the `draft` case). Pressing
**Build recipients** again — for example to add one more manual address, or
after picking up new source records — re-resolves the audience but drops
any address with an active exclusion, so a removed address does not
silently reappear. Manually re-adding that exact address is the one way to
undo this: an explicit add clears the exclusion, so it wins over the
earlier removal and a later rebuild keeps the address.

Adding is allowed for `draft`, `queued`, `sending` and `paused` campaigns —
a new row is simply picked up by the next outbox run. Suppressed
(unsubscribed or bounced) addresses are refused.

### Email validation

Addresses carry a validation status: `unknown`, `valid`, `invalid_syntax` or
`invalid_domain`.

- **Syntax** is checked automatically whenever recipients are built or added.
  It costs nothing and never touches the network.
- **Domains** are checked only when you press **Check domains**, which looks
  up MX records for every recipient. DNS is slow, so this is deliberately a
  button rather than something that happens during Build. Results are cached
  per domain for an hour, so a list of 500 addresses on a handful of domains
  costs a handful of lookups.

**Flagged addresses are still sent to.** The outbox does not skip them —
validation only tells you what looks undeliverable, and **Remove all
invalid** acts on it in one click. Nothing is dropped from a send without
you asking for it.

### Email placeholders

Templates and campaigns support these merge fields in both the subject and body:

| Placeholder | Renders as |
|---|---|
| `{{ name }}` | Recipient's full name (may be blank) |
| `{{ first_name }}` | First word of the recipient's name |
| `{{ email }}` | Recipient's email address |
| `{{ date }}` | Send date, e.g. July 19, 2026 |
| `{{ year }}` | Send year |
| `{{ unsubscribe_url }}` | Per-recipient unsubscribe link (appended automatically if omitted) |

Spacing is flexible — `{{name}}`, `{{ name }}` and `{{  name  }}` all work.
Unknown placeholders render as empty text rather than leaking a literal
`{{ typo }}` into a recipient's inbox; the editor warns about them when you
hit **Preview**, so check that before sending.

The editor stores what you author as `body_source` and derives the
CSS-inlined `body_html` that is actually sent, so editing is lossless and
re-saving never compounds inline styles. The **Source** button exposes the
raw HTML for pasted designs; switching back to the visual editor may
simplify markup Quill does not model. Alignment and indentation are
deliberately absent from the toolbar because email clients discard the CSS
classes Quill uses to implement them.

## Staff roles and permissions

Access to the admin panel is controlled by twelve **capabilities**. A
capability is an ordinary Django permission, defined once in
`brandtechsolution/staff/capabilities.py` — that module is the single source
of truth, feeding the permission rows, the `/api/staff/capabilities/` endpoint
and the UI's checkboxes, so the three cannot drift apart.

Capabilities are never granted to a person directly. They are ticked into a
**role** (an `auth.Group`), and people are given roles.

### The capabilities

| Codename | Label | What it gates |
|---|---|---|
| `manage_blog` | Manage blog posts | Creating, editing and deleting blog posts; also the panel's unfiltered post list, which is the only place drafts are visible |
| `publish_blog` | Publish blog posts | Changing a post's status — both draft → published and published → draft. Creating a post straight into `published` counts as a publish and needs it too |
| `manage_projects` | Manage projects | Creating, editing and deleting projects |
| `manage_appointments` | Manage appointments | The appointments list and the admin appointment management views |
| `view_inbox` | View inbox | Reading inquiries |
| `handle_inquiries` | Reply to and archive inquiries | Any write to an inquiry — replying, archiving, deleting |
| `manage_templates` | Manage email templates | Creating, editing and deleting email templates |
| `manage_campaigns` | Create and edit campaigns | Creating and editing campaigns; the default gate for every campaign action not listed below |
| `manage_recipients` | Manage campaign recipients | Building a campaign's audience and adding or removing individual recipients |
| `send_campaigns` | Send campaigns | Queueing, pausing and resuming a campaign — i.e. actually sending |
| `manage_tasks` | Assign and review tasks | Creating, assigning, editing and deleting tasks, and approving or sending back work that has been submitted for review. **Not** needed to see the task board or to do assigned work — see [Tasks](#tasks) |
| `manage_staff` | Manage staff and roles | Everything under **Staff & Roles**: roles, people, invitations and the activity log |

Note that `manage_campaigns` and `send_campaigns` are deliberately separate.
Sending is the one irreversible, externally visible action in the panel, so
editing a campaign and pushing it out the door are different permissions.

### Preset roles

Four roles are created by a data migration. They are ordinary groups: rename
them, re-tick their capabilities, delete them, or add your own.

| Role | Capabilities |
|---|---|
| **Editor** | `manage_blog`, `publish_blog`, `manage_projects` |
| **Marketing** | `manage_templates`, `manage_campaigns`, `manage_recipients` |
| **Support** | `view_inbox`, `handle_inquiries`, `manage_appointments` |
| **Administrator** | All twelve |

**Marketing deliberately does not include `send_campaigns`.** Sending is the
irreversible, externally visible action, so it starts reserved to
administrators. There is nothing special about it beyond that: it is an
ordinary capability and can be ticked into any role from the **Roles** tab.
The preset only decides the starting position.

Reversing the migration does not delete these groups. Once created they are
yours — a rollback that dropped them by name would take their memberships and
any customisation with them.

### Inviting someone

**Staff & Roles → Invite person**, then an email address and the roles they
should start with. The invitee gets a link and sets their own password; no
account exists until they do, and the password they choose must satisfy the
project's configured `AUTH_PASSWORD_VALIDATORS`.

- Links expire after **7 days**. The expiry lives in the signed token itself,
  so it needs no cleanup job. (`STAFF_INVITATION_MAX_AGE`, in seconds,
  overrides the default if you ever need a different window.)
- **Resend** issues a fresh link with a fresh 7-day window.
- **Revoke** deletes the invitation and invalidates its link.
- An invitation is **single-use**. Two people racing the same link produce one
  account, not two.
- If the address gets registered through the public `/signup/` page before the
  invitation is accepted, acceptance is refused with a clear message rather
  than failing obscurely — grant that existing account the roles instead. A
  resend is refused for the same reason, rather than mailing a link that would
  dead-end.
- The email is sent directly rather than through the campaign outbox, so it
  never queues behind a bulk send. If delivery fails the invitation row is
  kept so it can be resent, and the failure is written to the audit log.

### What a new account can see

**A staff account with no capabilities sees the dashboard and nothing else.**
That is the expected state for someone just invited and given no roles — not
a bug. Give them a role and the relevant sections appear.

### The rails

Three restrictions keep `manage_staff` safe to delegate.

**You can only grant capabilities you hold yourself.** A non-superuser cannot
hand out a capability they do not have. This applies in all three places a
grant can happen:

1. assigning roles to a person,
2. inviting someone with roles (a grant made before any account exists —
   otherwise you could invite a second address of your own and accept it),
3. adding a capability to a role (otherwise you could tick everything into a
   role you belong to and reload).

**Removing is always allowed.** De-escalation is never restricted, so an
administrator can still strip an account clean even if they do not personally
hold every capability being removed. This is the rail that makes delegating
`manage_staff` safe: a delegate can administer everyone else, but cannot
bootstrap themselves upward.

**Superuser accounts are protected.** A non-superuser holding `manage_staff`
cannot change a superuser's roles or active state — otherwise a delegate could
lock the owner out of their own site.

**You cannot lock yourself out.** A non-superuser cannot edit their own roles
or deactivate their own account. One flat rule, rather than
last-admin-standing arithmetic.

Superusers bypass every capability check (Django's `has_perm()` returns `True`
for them unconditionally) and are exempt from all three rails above. They are
the escape hatch, and can manage each other and themselves freely.

### Notes for maintainers

**`is_staff` is a required floor, in addition to any capability.** The site has
a public `/signup/` page that creates ordinary non-staff users, so a
capability alone is not enough: an account without `is_staff` is refused even
if it somehow holds the permission. Every enforcement path checks both.

**Nav gating is cosmetic.** The panel template hides sections a user cannot
use, and exposes the held set to JavaScript as `window.CAPABILITIES`. That is
a convenience, not the security boundary — every API enforces its own
capability independently on every request. Do not read the template's `{% if
can.x %}` blocks as enforcement.

Enforcement is spelled the way each layer wants it, but always means the same
thing:

- DRF views use `has_capability("codename")` from `staff/permissions.py`.
- Plain Django views use the `@capability_required("codename")` decorator from
  `staff/decorators.py`.
- The hand-rolled JSON views in `brand/api_views.py` call
  `capability_required_json(request, "codename")`.

### The audit log

Role and account changes are recorded in an **append-only** log, visible under
**Staff & Roles → Activity**. There is no update or delete route on it by
construction. Each entry's summary is rendered at write time, so it still
reads correctly after the user or role it names has been deleted.

Recorded: invitations sent, resent, failed to send, revoked and accepted; role
assignments changed; accounts deactivated and reactivated; roles created,
updated and deleted.

### Blog drafts

Blog posts are now created as **drafts** and need `publish_blog` to go live.
The public blog list and post pages show published posts only; a draft 404s
for the public. Someone with `manage_blog` but not `publish_blog` can write
and edit freely but cannot change a post's status in either direction.

## Tasks

**Tasks** is where work is handed out and signed off. It is the one panel
section every staff account can open, capability or not.

### Who sees what

| | No capability | `manage_tasks` |
|---|---|---|
| See the whole board and who is on what | ✅ | ✅ |
| Comment on any task | ✅ | ✅ |
| Mark **your own** part done | ✅ | ✅ |
| Create, assign, edit, delete | ❌ | ✅ |
| Approve or send back | ❌ | ✅ |

Reading is deliberately open. The board's value is that everyone can see what
the team is carrying, so hiding it behind a capability would mean granting
that capability to everybody — and with it the right to assign work.

### The status ladder

```
        assignees tick off their own part
OPEN ──────────────────────────────────────► IN REVIEW ──────────► DONE
  ▲            (all of them, not just one)                approve
  │
  └──────────────────────────────────────────────────────────┘
                    send back, with a reason
```

**Staff cannot reach DONE.** They mark their own share complete; the task
moves itself to *In review* once every assignee has done so, and only a
`manage_tasks` holder approves it. If people could close their own work there
would be nothing left to review.

Some consequences worth knowing:

- **Completion is per person.** With three people on a task, one finishing
  says nothing about whether the task is finished. The board shows
  "2 of 3 done".
- **Un-ticking pulls a task back out of review.** If someone decides they
  are not done after all, the task returns to *Open*.
- **Sending back clears every completion**, not just the submission. The work
  is going back to the whole group, so leaving people ticked off would bounce
  it straight into review again on the next save.
- **A reason is required to send back.** The people redoing the work need to
  be told what was wrong with it. It lands in the task's timeline.
- **An unassigned task never submits itself.** "Every assignee is finished" is
  vacuously true of nobody.
- **Status is not writable through the API.** `PATCH {"status": "done"}` is
  ignored — the ladder is only walked by the `complete`, `approve` and
  `reopen` actions, each of which enforces its own rule. Otherwise a task
  could read *Done* while its assignments were still outstanding.

### Being told about it

Two channels, both pointing at the same underlying state:

- **In panel** — a badge on the Tasks nav item. Reviewers see the count of
  tasks waiting on their approval; everyone else sees their own outstanding
  work.
- **Email** — everyone holding `manage_tasks` is mailed when a task enters
  review. Delivery failure is logged and swallowed: the review queue is the
  real signal, and a mail server problem must not roll back a submission a
  staff member legitimately made.

### API

Mounted at `/api/work/`. Every endpoint needs a staff account.

| Endpoint | Method | Gate |
|---|---|---|
| `/api/work/tasks/` | GET | any staff |
| `/api/work/tasks/` | POST | `manage_tasks` |
| `/api/work/tasks/{id}/` | PATCH, DELETE | `manage_tasks` |
| `/api/work/tasks/{id}/complete/` | POST | own assignment, or `manage_tasks` for anyone's |
| `/api/work/tasks/{id}/uncomplete/` | POST | own assignment, or `manage_tasks` |
| `/api/work/tasks/{id}/approve/` | POST | `manage_tasks` |
| `/api/work/tasks/{id}/reopen/` | POST | `manage_tasks`, `reason` required |
| `/api/work/tasks/{id}/activity/` | GET, POST | any staff |
| `/api/work/summary/` | GET | any staff (`needs_review` reads 0 without `manage_tasks`) |
| `/api/work/assignable/` | GET | any staff |

List filters: `?mine=1`, `?active=1` (everything not yet approved),
`?status=open|in_review|done`, `?assignee=<id>`, `?q=<search>`.

Only `is_staff`, active accounts can be assigned work — `/signup/` is public,
so `User` at large includes customers, and assigning one a task would put it
in a dashboard they cannot open.

### Upgrading an existing deployment

```bash
python manage.py migrate
```

`staff.0007` grants `manage_tasks` to the **Administrator** preset, so
existing administrators can use the section immediately. Editor, Marketing
and Support are left alone — assigning work is not part of any of them, so
tick it in from **Staff & Roles → Roles** if you want it there. Reversing the
migration removes that one grant and leaves the group and every hand-made
grant intact.

## 📝 License

This project is proprietary software for Brantech Solution.

## 🤝 Contributing

This is a private project. For contributions, please contact the project maintainers.

## 📧 Support

For issues or questions, please contact the development team.

---

**Status**: ✅ Production Ready - Website is fully functional and working correctly.
