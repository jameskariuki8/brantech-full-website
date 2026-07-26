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

## 📝 License & Contact

This repository is proprietary software for **Teklora Solutions Ltd**.

- **Email**: [teklorasolutionsltd@gamil.com](mailto:teklorasolutionsltd@gamil.com)
- **Phone**: +254 704 894220
- **Status**: ✅ Production Ready
