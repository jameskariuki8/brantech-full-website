# Teklora Solutions Fullstack Platform

This repository contains the enterprise Django web application for **Teklora Solutions Ltd** (formerly Brantech Solution) — a modern, high-performance platform for AI technology, software engineering, digital transformation, and technical consultation.

---

## ⚡ Recent System Enhancements & Release Notes

### ⚖️ Lawyer-Grade Legal & Statutory Compliance Framework
- **Privacy Policy Page** (`/privacy/` | `brand/templates/brand/privacy.html`):
  - Drafted under expert legal standards complying with the **Kenya Data Protection Act 2019 (KDPA)** and the **EU General Data Protection Regulation (GDPR)**.
  - Formatted into clean glassmorphic cards detailing Data Controller identification, legal processing bases (KDPA Sec. 30 & GDPR Art. 6), AES-256/TLS 1.3 encryption, 90-day telemetry retention, and Data Subject Access Request (DSAR) protocols.
- **Master Terms & Conditions Page** (`/terms/` | `brand/templates/brand/terms.html`):
  - Binding Master Service Agreement detailing Statements of Work (SOW), Intellectual Property assignment (Client Deliverables vs. Teklora Background IP), acceptable use policies, Net 30 payment schedules, liability caps, and dispute resolution via binding arbitration under the Nairobi Centre for International Arbitration (NCIA).

### 📬 Multi-Recipient Team Email Broadcasting
- Enhanced both contact inquiry submissions (`contact_submit`) and calendar consultation bookings (`create_appointment`) to automatically broadcast real-time notification emails to all 5 team email addresses simultaneously:
  - `juniorkariuki735@gmail.com`
  - `mugishalionel02@gmail.com`
  - `teklorasolutionsltd@gamil.com`
  - `leonmusungu138@gmail.com`
  - `davidnjihia536@gmail.com`

### 🎨 4-Column Footer & Global Chatbot Integration
- **Redesigned Footer**: Silicon Valley 4-column structure featuring company branding, social links (LinkedIn, Facebook, TikTok, Instagram), Quick Links, Services, Contact details, and explicit legal links (`/privacy/` and `/terms/`).
- **Updated Contact Email**: Global official email updated to `teklorasolutionsltd@gamil.com` across footer, contact page, privacy policy, and terms pages.
- **Site-Wide AI Chatbot Assistant**: Embedded reusable `chatbot.html` widget included inside `footer.html` for site-wide inheritance across all public pages.

### 📊 Admin Panel Restructuring
- **Display-Only Inbox**: Restructured inquiry cards to highlight client avatar badges, full name, mailto email link, tel phone link, timestamp, and message body; removed action buttons to focus on display.
- **Clean Appointments View**: Streamlined appointment cards by removing pending status pills, duration tags ("30 min"), and test titles, setting the Client's Full Name as the primary header.
- **Admin Sidebar Optimization**: Removed redundant Projects navigation link from the admin sidebar.

---

## 🚀 Key Features Overview

- **Silicon Valley Styled Portfolio & Services**: Modern, glassmorphic UI showcasing enterprise products, solutions, research, and technical services.
- **AI Content Scraping & Editorial Publishing Pipeline**: Automated content curation, AI-assisted article generation, markdown parsing, and capability-gated publishing.
- **Streamlined Appointment Booking System**: Virtual strategy consultation scheduling with real-time calendar availability checking and multi-recipient team notifications.
- **Multi-Recipient Notification Broadcasting**: Automatic notification dispatch to key team members on contact inquiries and consultation bookings.
- **Global AI Chatbot Assistant**: Embedded RAG-enabled floating chat widget powered by Google Gemini and ChromaDB vector embeddings.
- **Capability-Based Staff & Admin Control**: Fine-grained role-based access control (RBAC), security audit logs, staff invitations, and an interactive admin dashboard.
- **Legal & Compliance Infrastructure**: Market-standard, lawyer-drafted Privacy Policy (GDPR & Kenya Data Protection Act 2019 compliant) and Master Terms & Conditions.
- **Mobile-First Responsive Design**: Dynamic glassmorphism, responsive navigation menus, and adaptive card layouts for all screen sizes.

---

## 🤖 AI Editorial: Content Scraping & Publishing Pipeline

The platform includes an automated AI Editorial engine (`editorial/` & `ai_workflows/`) that automates content curation and publication:

```
┌──────────────────────────┐    ┌──────────────────────────┐    ┌──────────────────────────┐
│  Scrape & Discover       │───>│  AI Processing &         │───>│  Draft Review &          │
│  Industry Trends         │    │  Markdown Generation     │    │  Capability Publishing   │
└──────────────────────────┘    └──────────────────────────┘    └──────────────────────────┘
```

1. **Content Discovery & Scraping**: Ingests industry RSS feeds, technology trends, and engineering research topics.
2. **AI Content Generation**: Leverages Google Gemini and custom prompt pipelines to draft structured technical articles formatted in GitHub-flavored Markdown.
3. **Draft & Moderation Stage**: Generated posts enter the database as `draft` status, allowing editorial teams to review, edit, or approve.
4. **Capability-Gated Publishing**: 
   - Users with `manage_blog` can create and edit post contents.
   - Users with `publish_blog` can transition posts from `draft` to `published`, making them instantly available on the public site and updating the vector store embeddings.

---

## 📅 Streamlined Appointment Booking System

The appointment module (`appointments/`) provides an intuitive scheduling workflow for virtual strategy sessions:

- **Real-Time Availability Checking**: The `/appointments/check-availability/` endpoint validates date, time, and duration against active bookings to prevent overlapping slots.
- **Display-Only Admin Management**: Restructured admin list interface displaying Client Name, Email (clickable `mailto:`), Phone (clickable `tel:`), Date, Time, and Created timestamp without unnecessary buttons or test clutter.
- **Multi-Recipient Notification System**: Every booking automatically dispatches a real-time notification email to the primary admin and team members:
  - `juniorkariuki735@gmail.com`
  - `mugishalionel02@gmail.com`
  - `teklorasolutionsltd@gamil.com`
  - `leonmusungu138@gmail.com`
  - `davidnjihia536@gmail.com`

---

## 🎨 Complete Frontend Re-Engineering & Design System

The platform has undergone a complete architectural redesign for high visual impact and enterprise appeal:

- **Silicon Valley Design Aesthetic**: Built with modern dark mode (`#06090F`), smooth gradients, glassmorphism (`backdrop-filter: blur`), dynamic hover effects, and custom typography (Google Fonts *Inter* & *Outfit*).
- **4-Column Responsive Footer**: Includes company branding, social channels, Quick Links, Services, and direct legal links (`/privacy/` and `/terms/`).
- **Global AI Chatbot Widget**: Standalone reusable template (`chatbot.html`) included globally across all frontend pages via `footer.html`.
- **Lawyer-Drafted Legal Framework**:
  - **Privacy Policy** (`/privacy/`): Formatted under the **Kenya Data Protection Act 2019 (KDPA)** and **EU GDPR**, detailing Data Controller roles, legal processing grounds, AES-256/TLS 1.3 encryption, and Data Subject Access Request (DSAR) rights.
  - **Terms & Conditions** (`/terms/`): Formal Master Service Agreement covering Intellectual Property demarcation, acceptable use policies, payment schedules (Net 30), liability caps, and arbitration under the Nairobi Centre for International Arbitration (NCIA).

---

## 📱 Mobile Responsiveness & Adaptive UX

- **Fluid Grid Layouts**: Adaptive 1-column mobile layouts transitioning smoothly to multi-column desktop grids across forms, cards, and footers.
- **Mobile Navigation Drawer**: Responsive slide-over hamburger menu with smooth transitions for mobile viewports.
- **Collapsible Admin Sidebar**: Collapsible navigation bar with state persistence stored in `localStorage` for personalized workspace views.
- **Touch-Optimized Calendar**: Mobile-friendly date and time slot pickers with large touch targets.

---

## 🛠️ Technology Stack

- **Backend**: Django 5.2.7 (Python 3.13)
- **Database**: PostgreSQL with `pgvector` / SQLite (development)
- **AI / ML**: Google Gemini API, LangChain, LangGraph
- **Vector Database**: ChromaDB / PGVector
- **Styling**: Custom Vanilla CSS Design System (`redesign.css`) + Tailwind CSS (utilities)
- **API**: Django REST Framework

---

## 🛠️ Project Setup Guide

### Prerequisites

- Python 3.10+
- Virtual environment (`venv`)

### 1️⃣ Clone & Setup Environment

```bash
git clone https://github.com/jameskariuki8/brantech-full-website.git
cd brantech-full-website/brandtechsolution

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2️⃣ Environment Configuration

Copy `env.example` to `.env` and configure your credentials:

```ini
SECRET_KEY=your-secret-key-here
GOOGLE_API_KEY=your-google-gemini-api-key
DEBUG=True
ALLOWED_HOSTS=["127.0.0.1","localhost"]
```

### 3️⃣ Database & Vector Store Initialization

```bash
# Run database migrations
python manage.py migrate

# Initialize AI Vector Stores (Gemini embeddings)
python manage.py init_vector_stores

# Run development server
python manage.py runserver
```

Visit: **http://127.0.0.1:8000/**

---

## 🔌 Core API Endpoints

### Blog & Content API
- `GET /api/posts/` - List published blog posts
- `POST /api/posts/` - Create a blog post (`manage_blog` required)
- `GET /blog/<slug>/` - Server-rendered blog detail page

### AI Chatbot API
- `POST /api/ai/chat/` - Interactive RAG chatbot endpoint
- `GET /api/ai/chat/history/` - Retrieve session history

### Appointments API
- `POST /appointments/create/` - Book virtual consultation
- `POST /appointments/check-availability/` - Validate available slots
- `GET /appointments/` - Admin appointments list view (`manage_appointments` required)

### Contact & Messaging API
- `POST /contacts/submit/` - Public contact form submission (triggers multi-recipient email notifications)

---

## 🧪 Testing

```bash
# Run all test suites
python manage.py test

# Run specific app tests
python manage.py test messaging.tests.test_contact_submit
python manage.py test messaging.tests.test_inbox_escaping
python manage.py test appointments
```

---

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
| `manage_blog` | Manage blog posts | Creating, editing and deleting blog posts; the panel's unfiltered post list, which is the only place drafts are visible; and reading the AI newsroom at `/editorial/` — its dashboard, article previews, DOCX export and knowledge search |
| `publish_blog` | Publish blog posts | Changing a post's status — both draft → published and published → draft. Creating a post straight into `published` counts as a publish and needs it too. Also every newsroom action that decides what reaches the public site: approving an article (which publishes it), rejecting one, and triggering the pipeline, since it can auto-publish |
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


## 📝 License & Contact

This repository is proprietary software for **Teklora Solutions Ltd**.

- **Email**: [teklorasolutionsltd@gamil.com](mailto:teklorasolutionsltd@gamil.com)
- **Phone**: +254 704 894220
- **Status**: ✅ Production Ready
