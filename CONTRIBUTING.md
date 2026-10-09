# 🛠️ Teklora Engineering & Contributing Guide

Welcome to the **Teklora Solutions** development team. This document outlines our standard engineering workflow, repository conventions, and the mandatory update obligations required with every code contribution.

---

## 🧭 1. Development Workflow Overview

Development at Teklora is closely integrated with our internal platform. 

```
Teklora Admin Task → Git Branch → Code + Tests → Repo Docs Updated → Platform Review → Merged
```

1. **Find Assigned Task**: Locate your task in **Teklora Admin → Tasks** (`/admin-panel/?section=tasks`).
2. **Create Branch**: Create a feature/fix branch following the naming convention below.
3. **Build & Verify**: Implement the solution alongside unit/integration tests.
4. **Update Repository Contract Files**: Update `CHANGELOG.md`, `docs/ROADMAP.md`, or `README.md`.
5. **Mark Done on Platform**: Mark your assignment complete in the Teklora Admin panel to submit it for administrative review.

---

## 🌿 2. Branch & Commit Conventions

### Branch Naming
- `feat/<task-id>-<slug>` (e.g., `feat/task-42-staff-onboarding`)
- `fix/<task-id>-<slug>` (e.g., `fix/task-19-whatsapp-format`)
- `refactor/<task-id>-<slug>` (e.g., `refactor/task-05-agent-harness`)

### Commit Messages
Follow the Conventional Commits format with a clear reference to the platform Task ID:
```
<type>(<scope>): [Task #<id>] <short summary>

[optional detailed body]
```
*Example*:
```
feat(staff): [Task #42] add coding capabilities and WhatsApp prompt to onboarding flow
```

---

## 📜 3. The "Every-Update" Contract

Every Pull Request / codebase update must maintain repository hygiene by keeping the following files updated:

- [ ] **`CHANGELOG.md`**: Add concise bullet points under `## [Unreleased]` describing your changes (`Added`, `Changed`, `Fixed`, or `Security`).
- [ ] **`docs/ROADMAP.md`**: Mark any completed items `[x]` or update milestone progress.
- [ ] **`README.md`**: Update if changes affect public features, architecture diagrams, or environment configuration.
- [ ] **`docs/specs/`**: Ensure any new architectural decision or feature design has a corresponding specification in `docs/specs/`.

---

## 🧪 4. Testing & Quality Standards

Before submitting any code for review:
1. **Run App Tests**:
   ```bash
   python manage.py test <app_name>
   ```
2. **Run Full Test Suite**:
   ```bash
   python manage.py test
   ```
3. **Code Quality Rules**:
   - Write clean, type-hinted Python 3.12+ code adhering to PEP 8.
   - Do not catch general exceptions blindly (`except Exception: pass`). Log or fail explicitly.
   - Always validate phone numbers using the centralized `brandtechsolution/staff/phone.py` utility to ensure strict E.164 formatting.
   - Respect data protection standards (KDPA 2019 / GDPR).

---

## 👥 5. Review & Approval Process

1. When work on your branch is complete, open your PR.
2. In the Teklora Admin panel (`/admin-panel/?section=tasks`), mark your personal assignment on the task as completed.
3. Once all assignees mark complete, the task status automatically shifts to `In review`.
4. An Administrator reviews the code and task deliverables and marks the task `Done`.
