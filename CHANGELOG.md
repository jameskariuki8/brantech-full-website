# Changelog

All notable changes to the Teklora Solutions platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- **Contact UI & Interactive Experience Refinement**:
  - Unified the visual language of [`contacts.html`](brandtechsolution/brand/templates/brand/contacts.html) with modern dark/light glassmorphic tokens, ambient glow gradients, and cohesive `#007AFF` / `#00FF94` brand palettes.
  - Re-architected interactive Strategy Calendar modal with dynamic date initialization (`new Date()`), real-time day/slot selections, and touch-optimized controls.
  - Aligned global footer container in [`footer.html`](brandtechsolution/brand/templates/brand/footer.html) with standard `max-w-7xl` layout and enhanced mobile responsiveness for columns, legal links, and copyright notices.
  - Sized and refined the Partnership Application modal card (`#applyModalCard`) in [`partnerships.html`](brandtechsolution/brand/templates/brand/partnerships.html) with compact bounds (`max-w-lg`, `max-h-[85vh]`), dynamic track badge pill, reduced form paddings, and smooth inner scroll container to eliminate oversized vertical height on mobile and desktop viewports.
  - Fixed overlay ordering for strategic consultation modals: raised `calendarModal` and `bookingModal` z-index to `2000` to sit above the glassmorphic header, and added semi‑transparent `bg-surface/95` (light) / `dark:bg-[#090D16]/95` (dark) to the booking card for clearer visibility in light mode.
- **Staff & Roles panel redesigned around access levels** (`docs/specs/2026-10-12-staff-roster-access-levels-spec.md`):
  - People roster shows each person's derived level (Owner, Administrator, Member, No access), role chips, last sign-in, and setup/deactivated status, with search and filter chips that carry counts.
  - Person editor shows what each role grants, a live preview of the resulting access, and explains why controls are locked (editing yourself or an owner) instead of failing on save.
  - Roles tab lists the capabilities each role grants and links to the people who hold it.
  - Invitations waiting are separated from the roster; the editor becomes a bottom sheet on phones.
  - `GET /api/staff/people/` now includes read-only `last_login`.

### Fixed
- **Contact Page Layout & Modal Hierarchy**:
  - Resolved malformed DOM hierarchy in [`contacts.html`](brandtechsolution/brand/templates/brand/contacts.html) where modal bodies, turnstiles, and scripts were fragmented outside the document body.
  - Eliminated duplicate Strategy Calendar CTA buttons and repaired modal backdrop, dismissal triggers, and keyboard `Escape` bindings.
- **Onboarding now reaches every staff member**: the gate in `staff/middleware.py` skipped any staff account with no `StaffProfile` row, which covered everyone who existed before onboarding shipped and anyone created through `createsuperuser` or `/admin/`. A missing profile now counts as not onboarded, the onboarding page creates it on first visit, and superusers without `is_staff` (admitted to the panel by `brand.views.is_admin`) are gated and can complete it too.

### Added
- **Dedicated Partnerships & CSR Page (`/partnerships/`)**:
  - Engineered standalone, glassmorphic Partnerships and Corporate Social Responsibility hub (`brand/templates/brand/partnerships.html`) showcasing active partnership tracks, collaborative workflow, CSR pillars, partner logos, and an interactive application modal.
  - Replaced all emojis, font icon glyphs, and bullet symbols with exact, crisp inline vector `<svg>` elements across all badges, lifecycle steps, track cards, benefit/requirement checklists, and CSR feature cards.
  - Implemented dynamic database models `PartnershipType` and `PartnerOrganisation` supporting real-time admin management for open/closed tracks, benefits, criteria, and partner organizations.
  - Dedicated CSR mandate to organizations touching the lives of children (orphanages, rescue shelters, digital literacy, child safety) and ministries spreading the Gospel of Jesus Christ (churches, missionary societies, congregation tools).
  - Clarified EduShare status across the platform: explicitly established that EduShare is not currently zero-rated, launching a public call and partnership track for telecommunications carriers (Safaricom, Airtel, MTN) and educational donors to sponsor student data and zero-rate syllabus access across Kenya's 47 counties and the African continent.
  - Positioned CSR under the Partnerships ecosystem and wired global header dropdown and footer quick links directly to `/partnerships/`.
  - Added full Django Admin management interfaces with list filtering, ordering, and quick-access management buttons from the Teklora Admin panel (`admin_base.html` and `admin_site_content.html`).
- **Company & Corporate Navigation Restructuring**:
  - Reorganized the global navigation and footer from "About" to "Company", housing all company dimensions: *About Us & Story*, *Mission & Values*, *Careers & Jobs* (`/careers/`), *CSR & Social Impact* (`/about/#csr`), and *Partnerships*.
  - Updated [about.html](brandtechsolution/brand/templates/brand/about.html) with a direct link and action card for open roles linking directly to the full [Careers Page](brandtechsolution/brand/templates/brand/careers.html).
- **Mobile Navigation Modal Popup & Dropdown Redesign**:
  - Transformed mobile dropdown into a sleek, floating glassmorphism popup modal with full-screen dimming blur backdrop.
  - Sized compactly (`max-width: 380px`, reduced paddings, concise fonts) so the popup fits comfortably on phone screens without feeling oversized.
  - Added dedicated popup header featuring brand logo, title, and intuitive close button (`<i class="fas fa-times"></i>`).
  - Implemented collapsible accordion cards for dropdown items with smooth rotate transitions and sublink icons.
  - Added quick-access theme switch pill (`Dark / Light Mode`) and high-contrast consultation CTA button.
  - Added backdrop click, `Escape` key dismiss, and automatic background scroll locking for phone UX.
- **Careers Page & Admin Management Specification**:
  - Authored comprehensive specification ([`2026-10-11-careers-page-admin-management-spec.md`](docs/specs/2026-10-11-careers-page-admin-management-spec.md)) detailing the `JobOpening` model architecture, dynamic querying, and `/admin-panel/?section=careers` management hub.
  - Added Milestone 4 to [ROADMAP.md](docs/ROADMAP.md).
- **Staff GitHub Repository Scanning & Permission Discovery**:
  - Automatically scan repositories owned by staff members configured via `StaffProfile.github_username`.
  - Filter repositories to only include those where the platform's authenticated GitHub account has access (push/write, admin, maintain, or private pull access).
  - Categorize staff repositories with `role="staff"` and attach staff member attribution metadata (`username`, `staff_name`, `primary_role`).
  - Added dedicated `Staff` filter tab, metric badge counters, and owner chips in GitHub Manager admin dashboard (`/admin-panel/?section=githubSync`).
  - Synced staff projects automatically save with `github_role="staff"`.
- **Staff Onboarding & Capabilities Engine**:
  - Interactive onboarding wizard (`/staff/onboarding/`) prompting staff for WhatsApp number, primary engineering role, programming languages, and frameworks.
  - Comprehensive technology catalog covering AI/Computer Vision (OpenCV, PyTorch, Whisper, Gemini, RAG), Web & Backend (Django, FastAPI, Flask, DRF, Next.js, HTMX), Automation & Bots (Playwright, Browser-Use, WhatsApp/Telegram APIs, n8n), and Mobile/Desktop (Flutter, Android SDK, PySide6/Qt, Tauri).
  - Automatic Kenyan & international phone normalization to E.164 (`+254...`) with `wa.me` integration in the Admin panel.
  - Extended `StaffProfile` with `coding_languages`, `frameworks`, `primary_role`, `github_username`, `bio`, and `is_onboarded`.
  - Updated `MeSerializer` and Admin User Profile modal with real-time capability viewing and editing.
  - Onboarding gatekeeper middleware ensuring invited staff complete setup before navigating the panel.
- **Repository Engineering & Agent Infrastructure**:
  - `AGENTS.md` canonical instructions for AI pair-programming and autonomous workflows.
  - Universal symlinks for AI agents (`.cursorrules`, `CLAUDE.md`, `GEMINI.md`, `.agentrules`, `.github/copilot-instructions.md`).
  - `docs/ROADMAP.md` and `CONTRIBUTING.md` developer workflow guidelines.

---

## [1.2.0] - 2026-09-28

### Added
- **Lawyer-Grade Statutory Compliance Pages**:
  - Privacy Policy page (`/privacy/`) compliant with KDPA 2019 and GDPR.
  - Master Terms & Conditions page (`/terms/`) with dispute resolution under NCIA rules.
- **Multi-Recipient Notification Broadcasting**:
  - Site-wide contact inquiries and appointment bookings broadcast in real-time to all core engineering and executive inboxes.
- **Site-Wide AI Chatbot Assistant**:
  - Reusable glassmorphic AI chatbot widget embedded across all public page layouts.

### Changed
- **Admin Inbox Streamlining**: Converted inquiry cards to display-only view with copyable contact badges.
- **Admin Appointments View**: Cleaned appointment cards to prioritize client names and direct calendar management.

---

## [1.1.0] - 2026-08-04

### Added
- **Staff & Roles Management Engine (`staff`)**:
  - Granular capability-based permission system with audit logging and invitation tokens.
- **Multi-Assignee Task Tracking Pipeline (`tasks`)**:
  - Real-time task board with priority sorting, assignment completion tracking, and review approval workflows.
- **Email Campaign & Template Authoring Engine (`messaging`)**:
  - HTML email template builder and campaign audience segmentation.

---

## [1.0.0] - 2026-05-29

### Added
- Initial enterprise Django release of the Teklora Solutions platform.
- AI newsroom and automated editorial pipeline.
- Dockerized container setup and Cloudflare Tunnel routing.
