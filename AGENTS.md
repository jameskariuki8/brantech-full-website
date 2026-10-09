# Teklora Solutions — AI Agent & Engineering Instructions
> **Canonical Single Source of Truth for AI Assistants & Autonomous Agents**  
> *Note: This is the primary managed file. All other agent configuration files (`.cursorrules`, `CLAUDE.md`, `GEMINI.md`, `.agentrules`, `.github/copilot-instructions.md`) are symlinks pointing directly to this document.*

---

## 🏛️ 1. Project Overview & Architecture

Teklora Solutions Ltd is an enterprise Django fullstack web application and AI technology platform.

* **Backend**: Django 5.x / Python 3.12+ / SQLite (Dev) / PostgreSQL (Prod)
* **Frontend**: Django Templates + Tailwind CSS + Glassmorphism UI + Dynamic Components
* **AI & Agent Systems**: LangGraph checkpointers, Google Gemini API, Automated Editorial Pipeline (`editorial/`, `ai_workflows/`)
* **Task & Staff Management**: Native Teklora Admin (`/admin-panel/?section=tasks` and `?section=staff`)

---

## 📋 2. The "Every Update" File Maintenance Contract

Any developer or AI agent modifying code in this repository **must** adhere to the following update obligations:

1. **`CHANGELOG.md`**: Add an entry under `## [Unreleased]` for every new feature (`### Added`), modification (`### Changed`), or bugfix (`### Fixed`).
2. **`docs/ROADMAP.md`**: Check off completed items or add new milestone tasks when features are initiated or completed.
3. **`README.md`**: Update when user-facing features, architecture components, or environment variable setups change.
4. **`docs/specs/` & `docs/plans/`**: Create or update specifications and execution plans for all non-trivial features or architecture refactors before implementing.

---

## 🌿 3. Branch & Git Commit Standards

* **Branch Naming**: `<type>/<task-id>-<slug>`
  * Features: `feat/task-42-onboarding-flow`
  * Bug fixes: `fix/task-19-whatsapp-validation`
  * Refactoring: `refactor/task-12-agent-harness`
* **Commit Messages**: Conventional Commits standard referencing the task:
  * `feat(staff): [Task #42] add coding capabilities to staff onboarding`
  * `fix(tasks): [Task #19] resolve assignment review state transition`

---

## 🧪 4. Testing & Verification Standards

* **Run Tests**: Always execute automated tests for affected apps prior to declaring work complete:
  ```bash
  python manage.py test <app_name>
  ```
* **Linting & Code Style**:
  * Preserve existing comments and docstrings.
  * Follow Django best practices (explicit `related_name`, `db_index` on filtered fields, timezone-aware datetime).
  * Strict error handling: Never fail silently or swallow exceptions into empty dicts.
* **Security & Compliance**:
  * Adhere to Kenya Data Protection Act (KDPA 2019) and GDPR guidelines.
  * Ensure phone numbers are stored in E.164 format (e.g., `+254...`).
  * Ensure telemetry and logs respect user privacy.

---

## 👥 5. Platform Task & Staff Lifecycle Integration

1. Tasks are managed natively within **Teklora Admin → Tasks** (`brandtechsolution/tasks/`).
2. **Task Status Ladder**: `Open` $\rightarrow$ `In Review` $\rightarrow$ `Done`.
3. Developers/Agents mark individual `TaskAssignment` records complete.
4. Once all assignees mark complete, the task automatically transitions to `In Review`.
5. Only administrators (`manage_tasks` capability) approve tasks to `Done`.
