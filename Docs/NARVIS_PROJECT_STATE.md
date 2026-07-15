# NARVIS Project State

## Repository Status

| Field | Current value |
|---|---|
| Product | NARVIS AI Operating System |
| Current completed version | Version 1.4 |
| Development branch | `develop-v1.1` |
| Current checkpoint | Milestone 3: Runtime Observability complete |
| Checkpoint commit | `f5ffb5c` |
| Latest release tag | `v1.4-m3-sprint3` |
| Verified test baseline | 1,052 tests passing |
| Completed milestones | Milestones 1 through 3 |

Git history, source, and tests remain authoritative if this document becomes stale.

## Repository Health Summary

- The full suite passes: `python -m unittest discover -s Tests -p "test_*.py"` reports 1,052 passing tests.
- The checkpoint is committed, tagged, and synchronized with `origin/develop-v1.1`.
- The architecture remains modular, dependency-injected, provider-based, event-aware, deterministic, and backward compatible.
- Public compatibility aliases and legacy runtime paths remain available.
- Runtime diagnostics, service-registry snapshots, and capability manifests are
  passive, immutable, and metadata-only; they do not resolve services, probe
  providers, perform I/O, or grant execution authority.
- Optional voice, vision, internet, and host integrations may degrade safely when dependencies, credentials, hardware, or providers are unavailable.
- No configured Ruff, Black, Flake8, Pylint, or mypy gate is currently checked into the repository; `git diff --check` and the full tests are the reproducible repository gates.

## Current Architecture

`narvis.py` is the application composition root. It builds services through the existing dependency container, coordinates lifecycle startup and shutdown, publishes through the EventBus, and exposes health and structured logging.

Major architectural surfaces are:

- `Core/`: dependency injection, lifecycle, EventBus, configuration, plugins, structured logging, optimization, startup, and the Trusted Execution Gateway.
- `Core/diagnostics.py`, `Core/service_registry.py`, and `Core/capabilities.py`:
  passive runtime facts, dependency metadata, compatibility health, capability
  manifests, and deterministic readiness summaries.
- `AI/`: the backward-compatible Brain plus provider-agnostic AI Core,
  deterministic AI Routing, non-executing AI Orchestrator sessions and plans,
  built-in-provider compatibility adapters, and a typed Conversation bridge.
- `Agents/`: deterministic, planning-only task and workflow construction.
- `Skills/`: legacy skills plus typed discovery, matching, resolution, registry, and lifecycle management.
- `Execution/`: approval-bound execution sessions, immutable previews, risk summaries, readiness validation, and deterministic coordination state.
- `Conversation/`: immutable conversation/session models, history, context windows, topics, search, summaries, archive/export/cleanup, and lifecycle events.
- `Computer/`: provider-backed read-only information and desktop inspection while preserving legacy control APIs.
- `Memory/`, `Internet/`, `Voice/`, `Vision/`, `Automation/`, and `Dashboard/`: established runtime services behind injected abstractions and safe degraded defaults.
- `Evolution/`: observe-only discovery, planning, approval, verification, recovery, mutation validation, and simulations; it does not autonomously mutate the host.

## Completed Product Phases

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

## Completed Version 1.4 Milestones

| Milestone | Outcome | Status |
|---|---|---|
| Milestone 1: Repository Professionalization | Repository truth, onboarding, architecture, governance, roadmap, and recovery synchronization | Complete |
| Milestone 2: AI Runtime Integration | AI Manager composition, provider compatibility adapters, and Conversation-AI runtime bridge | Complete |
| Milestone 3: Runtime Observability | Runtime diagnostics, service registry, capability manifest, and readiness reporting | Complete |

### Milestone 1: Repository Professionalization

- Synchronized public, architecture, development, roadmap, state, handover, and
  recovery documentation around the verified repository checkpoint.
- Established the Version 1.4 milestone plan and preserved documentation-only
  scope for this milestone. Tag: `v1.4-milestone1`.

### Milestone 2: AI Runtime Integration

- Sprint 1 composed the Phase 13 AI Manager through the existing dependency
  container, lifecycle coordinator, EventBus, and logger while preserving the
  BrainEngine request path.
- Sprint 2 added passive, immutable compatibility adapters for built-in Brain
  providers and deterministic provider/fallback metadata.
- Sprint 3 added the typed Conversation-AI runtime bridge with detached AI
  lifecycle and availability metadata and no provider or execution edge.
- Tags: `v1.4-m2-sprint1`, `v1.4-m2-sprint2`, and `v1.4-m2-sprint3`.

### Milestone 3: Runtime Observability

- Sprint 1 added passive runtime diagnostics and deterministic metadata-only
  health summaries.
- Sprint 2 added the Runtime Service Registry, dependency graph summaries, and
  aggregate compatibility health without resolving services.
- Sprint 3 added the immutable Runtime Capability Manifest and deterministic
  readiness reports derived from diagnostics and registry metadata.
- Tags: `v1.4-m3-sprint1`, `v1.4-m3-sprint2`, and `v1.4-m3-sprint3`.

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

## Version 1.4 Release Status

Version 1.4 is complete at commit `f5ffb5c` and tag `v1.4-m3-sprint3` with
1,052 passing tests. The release composes architecture-only AI services and
adds passive observability while preserving the legacy Brain path,
deterministic tests, provider abstraction, Conversation ownership, public
compatibility, and every trusted execution boundary.

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
