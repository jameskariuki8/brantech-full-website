# Changelog

All notable changes to the Teklora Solutions platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Staff Onboarding & Capabilities Engine**:
  - Interactive onboarding wizard (`/staff/onboarding/`) prompting staff for WhatsApp number, primary engineering role, programming languages, and frameworks.
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
