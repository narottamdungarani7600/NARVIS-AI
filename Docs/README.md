# NARVIS Documentation Index

This directory contains the continuity, roadmap, decision, recovery, and AI
development policies for NARVIS. Repository code, tests, and Git history remain
the source of truth.

## Current Checkpoint

| Field | Value |
|---|---|
| Completed version | Version 1.4 |
| Completed phases | 1 through 13 |
| Branch | `develop-v1.1` |
| Latest release tag | `v1.4-m3-sprint3` |
| Test baseline | 1,052 passing tests |
| Completed milestones | Milestone 1: Repository Professionalization; Milestone 2: AI Runtime Integration; Milestone 3: Runtime Observability |

## Documentation Index

| Document | Purpose | Primary audience |
|---|---|---|
| [Repository README](../README.md) | Product overview, quick start, capabilities, roadmap, limitations, FAQ | Everyone |
| [Software Architecture](../SOFTWARE_ARCHITECTURE.md) | Layers, dependencies, subsystem contracts, trust boundaries | Architects and maintainers |
| [Project Development Guide](../PROJECT_DEVELOPMENT_GUIDE.md) | Engineering standards and end-to-end development workflow | Contributors |
| [Contributing](../CONTRIBUTING.md) | Contribution scope, review expectations, Git practices | Contributors |
| [Project State](NARVIS_PROJECT_STATE.md) | Current repository checkpoint, health, milestones, limitations | Maintainers and recovery sessions |
| [Development Roadmap](NARVIS_DEVELOPMENT_ROADMAP.md) | Completed milestones and explicitly future direction | Product and engineering |
| [Project Memory](PROJECT_MEMORY.md) | Compact continuity record and permanent guarantees | Recovery sessions |
| [Migration Handover](NARVIS_ACCOUNT_MIGRATION_HANDOVER.md) | Account/session handoff checkpoint | Maintainers |
| [Decision Ledger](NARVIS_DECISIONS.md) | Accepted architectural and safety decisions | Architects and reviewers |
| [AI Development Rules](AI_DEVELOPMENT_RULES.md) | Approval, safety, Git, documentation, and AI workflow policy | AI-assisted development |
| [Recovery Prompt](CODEX_RECOVERY_PROMPT.md) | Copyable instructions for a fresh development session | Recovery sessions |
| [Recovery Checklist](RECOVERY_CHECKLIST.md) | Concrete clone, interruption, and artifact checks | All contributors |
| [Changelog](../CHANGELOG.md) | Version, phase, sprint, and release history | Everyone |

## Recommended Reading Paths

### First-time contributor

1. Repository README.
2. This documentation index.
3. Project state and roadmap.
4. Software architecture.
5. Project development guide.
6. Contributing guide.
7. Relevant subsystem source and tests.

### Architecture review

1. Software architecture.
2. Decision ledger.
3. Project state and roadmap.
4. `narvis.py` composition root.
5. Relevant package contracts and regression tests.

### Recovery or new AI-assisted session

Follow the mandatory order in `AI_DEVELOPMENT_RULES.md`:

1. AI development rules.
2. Project memory.
3. Migration handover.
4. Project state.
5. Development roadmap.
6. Repository README and changelog.
7. Decision ledger, recovery prompt, and checklist.
8. Architecture and development guide.
9. Git, source, and test verification.

## Architecture Index

| Area | Primary paths | Architecture documentation |
|---|---|---|
| Composition, DI, lifecycle | `narvis.py`, `Core/system.py`, `Core/startup.py` | Sections 3 and 5 |
| Brain and AI providers | `AI/brain.py`, `AI/core/` | Sections 6 and 18 |
| AI routing and orchestration | `AI/routing/`, `AI/orchestrator/`, `AI/compatibility.py`, `AI/runtime.py` | Section 18 |
| Conversation | `Conversation/core/`, `Conversation/context/`, `Conversation/lifecycle/` | Section 17 |
| Planning | `Skills/core/`, `Agents/core/` | Sections 11 and 12 |
| Trusted and Safe Execution | `Core/execution/`, `Execution/` | Sections 16 and 22 |
| Computer and desktop | `Computer/core/`, `Computer/services/`, `Computer/desktop/` | Sections 13 and 14 |
| Runtime capabilities | `Memory/`, `Internet/`, `Voice/`, `Vision/`, `Automation/` | Sections 7-10 and 15 |
| Operations | `Core/diagnostics.py`, `Core/service_registry.py`, `Core/capabilities.py`, `Dashboard/`, `Core/logger.py`, `Core/plugins.py` | Sections 5, 19-21, and 24 |
| Evolution | `Evolution/` | Project state, roadmap, and decisions |

Section numbers refer to [SOFTWARE_ARCHITECTURE.md](../SOFTWARE_ARCHITECTURE.md).

## Workflow Index

- Quick start and local setup: repository README.
- Architecture and implementation standards: project development guide.
- Contribution and review checklist: contributing guide.
- Test baseline: project state and repository README.
- Git, commit, push, and release gates: project development guide.
- Recovery and interrupted work: recovery prompt and checklist.
- Current/future product scope: project state and roadmap.

## Engineering Governance Index

| Governance topic | Authoritative document |
|---|---|
| Architecture invariants and module ownership | [Software Architecture](../SOFTWARE_ARCHITECTURE.md) sections 31-32 |
| Allowed dependency directions and layer boundaries | [Software Architecture](../SOFTWARE_ARCHITECTURE.md) sections 3, 5, and 31 |
| Backward compatibility and versioning | [Project Development Guide](../PROJECT_DEVELOPMENT_GUIDE.md) section 21 |
| Branch, Git, and release workflow | [Project Development Guide](../PROJECT_DEVELOPMENT_GUIDE.md) sections 18-21 |
| Repository quality gates and testing policy | [Project Development Guide](../PROJECT_DEVELOPMENT_GUIDE.md) section 22 |
| Architecture, code, sprint, and release checklists | [Project Development Guide](../PROJECT_DEVELOPMENT_GUIDE.md) section 23 |
| Contributor expectations and review handoff | [Contributing](../CONTRIBUTING.md) |
| Permanent safety and approval rules | [AI Development Rules](AI_DEVELOPMENT_RULES.md) |
| Accepted architecture decisions | [Decision Ledger](NARVIS_DECISIONS.md) |

## Governance Maintenance

- Architecture invariants change only through an approved architecture proposal,
  decision record, compatibility analysis, migration/recovery plan, and full
  regression validation.
- Workflow or quality-gate changes must update the development guide,
  contributing guide, and this index together.
- Adding a formatter, linter, type checker, coverage threshold, CI service, or
  release automation is an engineering change, not a documentation shortcut.
- Branch names and historical tags must be verified from Git before documenting
  a branch or release policy.
- Future contributors must provide evidence for scope, compatibility, tests,
  documentation, and repository hygiene claims.

## Documentation Maintenance

When a sprint changes repository truth:

1. Update the project state and roadmap.
2. Update public overview and architecture documents when their claims change.
3. Add version or sprint history to the changelog.
4. Update recovery checkpoints, test counts, tags, and important source paths.
5. Check relative links, code fences, heading structure, and `git diff --check`.
6. Confirm documentation does not claim future functionality as implemented.

## Current Scope Boundary

Version 1.4 is complete. Milestone 1: Repository Professionalization,
Milestone 2: AI Runtime Integration, and Milestone 3: Runtime Observability are
implemented at `v1.4-m3-sprint3`. Version 1.5 commercial objectives and any
post-Version 1.4 provider execution or hardening remain roadmap proposals until
separately designed and approved. They do not authorize runtime, API,
architecture, execution, commit, push, or release changes.
