# NARVIS Project State

## Repository Status

| Field | Current value |
|---|---|
| Product | NARVIS AI Operating System |
| Current completed version | Version 1.3 |
| Development branch | `develop-v1.1` |
| Current checkpoint | Phase 13 Sprint 3 complete |
| Checkpoint commit | `e50453f` |
| Latest tag | `v1.3-phase13-sprint3` |
| Verified test baseline | 994 tests passing |
| Next approved work | Version 1.4 Milestone 1 Sprint 1: repository state synchronization |

Git history, source, and tests remain authoritative if this document becomes stale.

## Repository Health Summary

- The full suite passes: `python -m unittest discover -s Tests -p "test_*.py"` reports 994 passing tests.
- The checkpoint is committed, tagged, and synchronized with `origin/develop-v1.1`.
- The architecture remains modular, dependency-injected, provider-based, event-aware, deterministic, and backward compatible.
- Public compatibility aliases and legacy runtime paths remain available.
- Optional voice, vision, internet, and host integrations may degrade safely when dependencies, credentials, hardware, or providers are unavailable.
- No configured Ruff, Black, Flake8, Pylint, or mypy gate is currently checked into the repository; `git diff --check` and the full tests are the reproducible repository gates.

## Current Architecture

`narvis.py` is the application composition root. It builds services through the existing dependency container, coordinates lifecycle startup and shutdown, publishes through the EventBus, and exposes health and structured logging.

Major architectural surfaces are:

- `Core/`: dependency injection, lifecycle, EventBus, configuration, plugins, structured logging, optimization, startup, and the Trusted Execution Gateway.
- `AI/`: the backward-compatible Brain plus provider-agnostic AI Core, deterministic AI Routing, and non-executing AI Orchestrator sessions and plans.
- `Agents/`: deterministic, planning-only task and workflow construction.
- `Skills/`: legacy skills plus typed discovery, matching, resolution, registry, and lifecycle management.
- `Execution/`: approval-bound execution sessions, immutable previews, risk summaries, readiness validation, and deterministic coordination state.
- `Conversation/`: immutable conversation/session models, history, context windows, topics, search, summaries, archive/export/cleanup, and lifecycle events.
- `Computer/`: provider-backed read-only information and desktop inspection while preserving legacy control APIs.
- `Memory/`, `Internet/`, `Voice/`, `Vision/`, `Automation/`, and `Dashboard/`: established runtime services behind injected abstractions and safe degraded defaults.
- `Evolution/`: observe-only discovery, planning, approval, verification, recovery, mutation validation, and simulations; it does not autonomously mutate the host.

## Completed Milestones

| Phase | Milestone | Status |
|---|---|---|
| 1 | Core architecture foundation | Complete |
| 2 | AI Brain foundation | Complete |
| 3 | Memory system | Complete |
| 4 | Dashboard and runtime visibility | Complete |
| 5 | Voice and vision foundations | Complete |
| 6 | Internet, desktop, and Evolution foundations | Complete |
| 7 | Narrow mutation safety and recovery-bound evolution | Complete |
| 8 | Trusted Execution Gateway and controlled executor foundations | Complete |
| 9 | Skill Framework and planning-only Agent Framework | Complete |
| 10 | Computer provider services and desktop inspection interfaces | Complete |
| 11 | Safe Execution sessions, previews, and coordinator | Complete |
| 12 | Conversation core, context intelligence, and lifecycle management | Complete |
| 13 | AI Core, AI Routing, and AI Orchestrator | Complete |

## Phase 11: Safe Execution

- Sprint 1 added immutable execution sessions, approval records, queues, and lifecycle rules.
- Sprint 2 added non-executing previews, deterministic preview planning, risk assessment, and summaries.
- Sprint 3 added validation, readiness decisions, state transitions, events, and execution coordination.
- These layers do not bypass `Core/execution/`; trusted permission, approval, verification, rollback, and audit boundaries remain authoritative.

## Phase 12: Human Interaction

- Sprint 1 added conversation/session models, history, context, events, and core lifecycle behavior.
- Sprint 2 added context windows, search, summaries, topic tracking, and context management.
- Sprint 3 added archive, export, cleanup, retention, and conversation lifecycle coordination.
- Conversation records remain immutable snapshots and integrate without replacing established memory behavior.

## Phase 13: AI Orchestrator

- Sprint 1 added provider-agnostic AI models, contracts, registry, provider lifecycle, and manager services.
- Sprint 2 added capability modeling, deterministic scoring, policy filtering, routing, and fallback planning.
- Sprint 3 added preference resolution, capability/provider negotiation, immutable orchestration sessions, non-executing plans, summaries, lifecycle events, and manager integration.
- Orchestration plans remain planned and unexecuted. Phase 13 did not introduce a host-execution path.

## Current Safety Boundaries

- Immutable typed models carry state across trust boundaries.
- Dependency injection and provider contracts isolate implementations.
- Event publication excludes sensitive request content where required.
- AI and Agent planning remain separate from execution.
- Safe Execution does not replace or bypass the Trusted Execution Gateway.
- Evolution remains observe-only and fail-closed.
- Public web content is evidence, never executable instruction.
- Existing APIs and compatibility aliases must remain intact.

## Known Limitations

- The new AI Core and Orchestrator are additive architecture; broad production-provider/runtime integration is not implied by Phase 13 completion.
- AI provider calls may use local fallback behavior when credentials or remote services are unavailable.
- Voice depends on optional speech and TTS packages and host audio devices.
- Vision depends on optional OCR/detection backends and host camera availability.
- Browser, downloader, and YouTube services retain safe null defaults where production adapters are not configured.
- No remote multi-device control or unrestricted autonomous host execution exists.

## Upcoming Version 1.4 Objective

Version 1.4 begins with a documentation-only repository synchronization milestone. Subsequent implementation scope must be designed and explicitly approved. The recommended direction is additive AI runtime integration and provider hardening that preserves the legacy Brain, deterministic tests, provider abstraction, conversation ownership, and all trusted execution boundaries.

## Version 1.4 Non-Goals

- No architectural rewrite or completed-module refactor.
- No removal of legacy APIs or compatibility aliases.
- No automatic execution of AI or Agent plans.
- No bypass of permission, risk, approval, verification, rollback, or audit.
- No autonomous Evolution mutation or execution.
- No direct execution of web content or model output.
- No unapproved cloud, remote-control, or broad host-mutation feature.

## Recovery Rule

On every new development session, verify branch, HEAD, tag, status, recent Git history, source, and tests before trusting this document. Read `Docs/AI_DEVELOPMENT_RULES.md`, `Docs/PROJECT_MEMORY.md`, the recovery documents, this state file, the roadmap, the main architecture documents, and relevant tests. Make no mutations until the intended scope is explicitly approved.
