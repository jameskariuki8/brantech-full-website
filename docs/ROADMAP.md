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

### 🧠 Milestone 2: Unified Agent Harness & Editorial Intelligence *(Completed)*
- [x] **Unified Model Harness**:
  - [x] Centralize model execution, routing, and provider abstraction into `ai_workflows/harness/` (`docs/specs/2026-09-21-unified-agent-harness-design.md`).
  - [x] Multi-provider configuration supporting Gemini, Anthropic, OpenAI, DeepSeek, OpenRouter, and Codex.
  - [x] Unified exponential backoff, rate-limit retry policies, and automated admin failure alerts (`alerts.py`).
  - [x] Newsroom agent migration across 6 core editorial/research agents removing isolated model clients and fallbacks.
- [x] **Persistent Semantic Knowledge Base & Memory**:
  - [x] Single-corpus semantic memory with per-vector model provenance (`memory.py`).
  - [x] Scored re-embedding on model switch with vector indexing.
  - [x] Token usage accounting, pricing catalog (`pricing.toml`), and budget tracking (`usage.py`).

---

### 💻 Milestone 3: GitHub Manager & Developer Portal *(In Progress)*
- [ ] **GitHub Admin Panel Integration** (`/admin-panel/?section=githubSync`):
  - [x] Live repository management dashboard with search, filtering, and project conversion.
  - [x] Background sync, commit counts tracking, and interactive README markdown inspector (`brand/github_service.py`).
  - [ ] Staff GitHub repository discovery: scan and import accessible repositories from configured staff GitHub profiles.
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
