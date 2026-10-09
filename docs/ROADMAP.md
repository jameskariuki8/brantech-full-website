# 🗺️ Teklora Platform Roadmap

This document serves as the high-level roadmap and strategic milestone tracker for Teklora Solutions Ltd. It aligns repository development with the platform's internal task pipeline (`/admin-panel/?section=tasks`).

---

## 🎯 Active & Upcoming Milestones

### 🚀 Milestone 1: Staff Onboarding & Capability Profile Matrix *(Completed)*
- [x] **Technical / Coding Capabilities Matrix**:
  - [x] Add coding capabilities schema (languages, frameworks, primary role, GitHub handle) to `StaffProfile`.
  - [x] Support primary programming languages, frameworks, and skill bio in profile API and admin view.
- [x] **WhatsApp Communication Setup**:
  - [x] Integrate WhatsApp number collection in onboarding flow with E.164 sanitization & validation (`phone.py`).
  - [x] Add quick-action WhatsApp button to Staff directory in Admin panel (`wa.me` integration).
- [x] **Interactive Onboarding UI**:
  - [x] Onboarding redirect (`/staff/onboarding/`) for staff accounts.
  - [x] Capability selection pill-selector and comprehensive profile completion form.

---

### 🧠 Milestone 2: Unified Agent Harness & Editorial Intelligence *(In Design / Spec)*
- [ ] **Unified Model Harness**:
  - [ ] Unify LangGraph checkpointer and newsroom services into a single reusable agent orchestrator (`docs/specs/2026-09-21-unified-agent-harness-design.md`).
  - [ ] Centralize Gemini model configuration, retry strategies, and rate-limit backoffs.
- [ ] **Persistent Semantic Knowledge Base**:
  - [ ] Connect `KnowledgeDocument` vector search into active chat workflows.
  - [ ] Dynamic episodic memory checkpointer for long-term customer interactions.

---

### 💻 Milestone 3: GitHub Manager & Developer Portal *(Upcoming)*
- [ ] **GitHub Admin Panel Section** (`/admin-panel/?section=github`):
  - [ ] Live commit feed and release tag status across Teklora repositories.
  - [ ] Automated PR status linking with Teklora Admin Tasks.
- [ ] **Client Project Delivery Hub**:
  - [ ] Client-facing milestone tracking and deliverable inspection.

---

## ✅ Completed Milestones

- [x] **Statutory Compliance & Legal Engine**: KDPA 2019 & GDPR compliant Privacy Policy and Terms of Service.
- [x] **Multi-Team Real-Time Email Broadcast**: Instant email alerts to all engineering inboxes for incoming client inquiries.
- [x] **Staff & Role-Based Access Control**: Granular capability system with immutable audit logging.
- [x] **Multi-Assignee Task Board**: Status ladder (`Open` → `In Review` → `Done`) with per-assignee completion tracking.
- [x] **Cloudflare Tunnel & Dockerization**: Production-ready containerized deployment configuration.
