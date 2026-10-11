# Changelog

All notable changes to the Teklora Solutions platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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
