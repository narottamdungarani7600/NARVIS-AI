# NARVIS AI Operating System

NARVIS is a modular Python AI assistant runtime that combines reasoning,
conversation, memory, voice, vision, internet research, skills, planning,
computer integration, automation, and operational visibility behind explicit
contracts and safety boundaries.

| Repository status | Value |
|---|---|
| Current completed version | Version 1.4 |
| Current checkpoint | Milestone 3: Runtime Observability complete |
| Completed phases | 1 through 13 |
| Development branch | `develop-v1.1` |
| Latest release tag | `v1.4-m3-sprint3` |
| Verified test baseline | 1,052 passing tests |
| Language | Python 3.10+ |
| License | MIT |

## Project Overview

NARVIS is an architecture-first foundation for an AI operating environment.
Its implemented runtime can classify and route requests, maintain conversation
and memory context, use registered skills, access provider-backed internet and
computer services, coordinate voice and vision foundations, expose dashboard
health, and model controlled execution through typed safety layers.

Version 1.4 completes Repository Professionalization, AI Runtime Integration,
and Runtime Observability. The Phase 13 AI Manager is composed through the
existing dependency injection and lifecycle boundaries, built-in Brain
providers are exposed through passive compatibility adapters, Conversation can
carry detached AI runtime metadata, and immutable diagnostics, service-registry,
and capability-manifest snapshots describe runtime readiness. These additions
preserve the Brain execution path, public APIs, and Trusted Execution Gateway.

This repository is a local modular runtime, not a hosted commercial service.
Features requiring credentials, optional libraries, hardware, or production
providers degrade safely or use explicit null/fallback implementations.

## Vision

The project aims to provide a maintainable base in which reasoning,
interaction, memory, capabilities, planning, perception, and controlled
execution can evolve independently. Growth must preserve:

- immutable typed models at important boundaries;
- dependency injection and provider abstraction;
- deterministic behavior and isolated tests;
- lifecycle management, structured logging, and EventBus observability;
- public API and compatibility guarantees;
- explicit permission, approval, verification, rollback, and audit controls.

## Implemented Capability Summary

| Area | Implemented scope |
|---|---|
| AI | Brain pipeline, intent routing, prompts, responses, provider abstractions, AI Core, deterministic Routing, non-executing Orchestrator sessions/plans, compatibility adapters, and Conversation runtime metadata |
| Conversation | Immutable sessions and history, context windows, search, summaries, topics, archive, export, cleanup, and lifecycle coordination |
| Memory | Short-term, long-term, session, profile, persistence, search, ranking, recovery, and context-summary integration |
| Skills and Agents | Built-in skills, typed discovery/resolution/lifecycle, and dependency-aware planning without plan execution |
| Safe Execution | Approval-bound sessions, queues, previews, risk/readiness models, state transitions, and coordination |
| Trusted Execution | Permission, risk, policy, approval, optional dispatch, verification, rollback, audit, and lifecycle events |
| Computer and Automation | Provider-backed read-only information, desktop inspection, compatible legacy controls, workspace automation, schedules, tasks, and workflows |
| Internet | HTTP abstraction, search fallback, grounded research, news, weather, Wikipedia, safety, caching, and diagnostics |
| Voice and Vision | Replaceable speech/audio services, wake words, camera/screenshots, image processing, OCR abstraction, detection, and safe degraded defaults |
| Operations | Composition root, dependency container, lifecycle, plugins, structured logging, passive diagnostics, service registry, capability manifest, health checks, optimization, and dashboard services |
| Evolution | Observe-only discovery, proposals, approvals, planning, verification, recovery, validation, and simulations; no autonomous host mutation |

## AI Operating System Architecture

```text
User and integration surfaces
  -> Brain, Conversation, and AI orchestration
  -> Skills, Agents, and capability planning
  -> Memory, Internet, Computer, Automation, Voice, and Vision
  -> Safe Execution coordination
  -> Trusted Execution Gateway
  -> explicitly injected provider or dispatcher

Core infrastructure supports every layer:
DependencyContainer | Lifecycle | EventBus | Logging | Plugins | Diagnostics
```

Planning, routing, previewing, and orchestration records do not grant execution
authority. Executable requests remain subject to the Trusted Execution Gateway.

### Dependency Flow

- `narvis.py` is the application composition root.
- Core infrastructure may be depended on by domain packages.
- High-level managers depend on protocols, registries, and injected services.
- Providers implement domain contracts; domain services do not depend on a
  specific production provider.
- Presentation and orchestration call domain facades rather than low-level host
  implementations directly.
- Execution flows inward through typed validation and trust boundaries before
  an explicitly registered dispatcher can be reached.
- Tests inject clocks, identifiers, providers, loggers, and event publishers to
  preserve deterministic behavior.

See [SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md) for subsystem contracts
and [Docs/README.md](Docs/README.md) for the complete documentation map.

## Repository Structure

```text
NARVIS/
|-- Agents/core/              # Planning-only Agent Framework
|-- AI/                       # Brain plus AI Core, Routing, Orchestrator
|-- Automation/               # Tasks, scheduling, workflows, workspace actions
|-- Computer/                 # Provider services, desktop inspection, legacy controls
|-- Config/                   # Application configuration
|-- Conversation/             # Core, context intelligence, lifecycle
|-- Core/                     # DI, lifecycle, events, logging, plugins, execution
|-- Dashboard/                # Runtime health and operational presentation
|-- Docs/                     # State, roadmap, decisions, recovery, onboarding
|-- Evolution/                # Observe-only evolution and simulations
|-- Execution/                # Sessions, previews, coordinator
|-- Internet/                 # Search, research, providers, safety
|-- Memory/                   # Persistence, retrieval, ranking, context recovery
|-- Skills/                   # Built-ins and typed skill framework
|-- Tests/                    # Unit and integration regression suite
|-- Vision/                   # Capture, image processing, OCR, detection
|-- Voice/                    # Audio, STT, TTS, wake words, sessions
|-- main.py                   # Process entry point
`-- narvis.py                 # Application composition root
```

## Quick Start

### Prerequisites

- Python 3.10 or newer
- Git
- Windows for the currently implemented desktop-oriented integrations
- Optional audio, camera, OCR, and provider dependencies for corresponding
  hardware or external-service capabilities

### Set up the repository

```powershell
git checkout develop-v1.1
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Verify the checkout

```powershell
python -m unittest discover -s Tests -p "test_*.py"
git diff --check
```

The Version 1.4 checkpoint should report 1,052 passing tests. Optional voice,
vision, or device warnings can occur when local dependencies or hardware are
unavailable; they should not fail the deterministic test suite.

### Run NARVIS

```powershell
python main.py
```

The process constructs registered services, starts the managed runtime, opens
the current dashboard surface, and performs coordinated shutdown when closed.

## Local Development

1. Read [Docs/README.md](Docs/README.md) and the current project state.
2. Confirm branch, HEAD, tag, and working-tree status from Git.
3. Define the smallest architecture-aligned scope and obtain required approval.
4. Add or update deterministic tests for behavior changes.
5. Run focused tests during development and the complete suite before handoff.
6. Run `git diff --check` and inspect the entire diff.
7. Update architecture, roadmap, recovery, and public documentation as needed.
8. Treat implementation, commit, push, and tag as separate approval gates.

Detailed standards are in
[PROJECT_DEVELOPMENT_GUIDE.md](PROJECT_DEVELOPMENT_GUIDE.md); contribution
expectations are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Testing Workflow

Run one focused module while iterating:

```powershell
python -m unittest Tests.test_ai_orchestrator
```

Run the release baseline before completion:

```powershell
python -m unittest discover -s Tests -p "test_*.py"
git diff --check
```

No dedicated Ruff, Black, Flake8, Pylint, or mypy configuration is currently
checked into the repository. Do not claim those gates passed unless a future
approved milestone adds and runs them.

## Engineering Governance

NARVIS development is governed by repository invariants rather than informal
convention:

- `narvis.py` remains the explicit composition root.
- Modules own one domain responsibility and depend on stable contracts.
- Concrete providers are injected and registered at composition boundaries.
- Important state is represented with validated immutable models.
- Planning, routing, negotiation, previewing, and simulation do not grant
  execution authority.
- Trusted execution, lifecycle, EventBus, logging, and compatibility boundaries
  may not be bypassed by new features.
- Public APIs and aliases remain compatible unless an approved major-version
  migration explicitly changes them.

New modules require ownership and dependency analysis, architecture approval,
deterministic tests, documentation, and independent validation before runtime
composition. Internal algorithms and optional providers may evolve when their
contracts, ordering, failure behavior, and compatibility remain preserved.

### Repository quality gates

| Gate | Minimum completion evidence |
|---|---|
| Scope | Only approved files and behavior changed |
| Architecture | Ownership, dependencies, invariants, and trust boundaries reviewed |
| Compatibility | Existing APIs, aliases, commands, events, and configuration preserved |
| Verification | Focused tests and the complete accepted baseline pass |
| Documentation | Public, architecture, state, roadmap, changelog, and recovery claims agree as applicable |
| Hygiene | `git diff --check` passes and no runtime artifacts or secrets are included |
| Release | Commit, push, merge, and tag occur only through separate approvals |

The full architecture review, code review, sprint completion, and release
readiness checklists are maintained in
[PROJECT_DEVELOPMENT_GUIDE.md](PROJECT_DEVELOPMENT_GUIDE.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

## Version and Milestone History

| Version | Phases or milestones | Major outcome | Test checkpoint |
|---|---:|---|---:|
| 1.1 | 1-8 | Modular runtime foundation and Trusted Execution Gateway | 559 |
| 1.2 | 9-12 | Skills/Agents, Computer/Desktop, Safe Execution, Conversation | Historical intermediate baselines |
| 1.3 | 13 | AI Core, deterministic Routing, and non-executing Orchestrator | 994 |
| 1.4 | M1-M3 | Repository Professionalization, AI Runtime Integration, and Runtime Observability | 1,052 |
| 1.5 | Future objective | Commercial-readiness work such as packaging, deployment, operations, supportability, and security review | Not implemented |

The Version 1.5 row is a future product objective, not a claim that packaging,
hosting, billing, enterprise administration, or commercial operations exist.

## Roadmap

### Version 1.4 completed scope

- **Milestone 1: Repository Professionalization** synchronized repository
  truth, onboarding, architecture navigation, governance, and recovery records.
- **Milestone 2: AI Runtime Integration** composed the AI Manager, added passive
  built-in-provider compatibility adapters, and connected architecture-only AI
  sessions to Conversation metadata without replacing the Brain path.
- **Milestone 3: Runtime Observability** added passive runtime diagnostics, a
  metadata-only service registry, and an immutable capability manifest with
  deterministic readiness reporting.

Version 1.4 is complete at `v1.4-m3-sprint3`. Later provider execution,
production hardening, or broader operational work requires separate scope and
approval.

### Version 1.5 commercial objective

The proposed Version 1.5 objective is to evaluate and implement the operational
work needed to deliver NARVIS as a supportable commercial product. Candidate
scope includes packaging, deployment, configuration/secrets management,
observability, upgrade/rollback procedures, security review, service-level
definition, and support documentation. None of this candidate scope is approved
or implemented merely because it appears here.

## Commercial Use Cases

The current architecture can serve as a foundation for evaluated product work
in these areas:

- a local AI assistant with modular memory and conversation services;
- a controlled desktop productivity assistant using explicit host adapters;
- an internal research assistant using grounded internet provider abstractions;
- an extensible capability platform built from registered skills and providers;
- a planning and approval interface for workflows that require auditable trust
  boundaries;
- a reference architecture for testing provider routing and AI orchestration.

Production suitability depends on the chosen providers, deployment model,
security controls, operational requirements, and validation. These are use-case
directions, not claims of turnkey commercial readiness.

## Known Limitations

- AI calls depend on configured providers and credentials and may fall back
  locally when unavailable.
- Voice depends on optional speech/TTS libraries and host audio devices.
- Vision depends on camera access and optional OCR or detection backends.
- Browser opening, downloads, and YouTube may use null providers by default.
- Desktop integrations are currently Windows-oriented.
- The Phase 13 AI Orchestrator is architecture-only and does not execute plans.
- Evolution remains observe-only and cannot autonomously mutate the host.
- Remote multi-device control, hosted service operations, billing, tenant
  management, and commercial deployment automation are not implemented.

## Explicit Non-Goals

- Rewriting the established architecture or refactoring completed phases.
- Removing public APIs, legacy paths, or compatibility aliases.
- Executing raw model output, public web content, plans, or previews directly.
- Bypassing permission, risk, approval, verification, rollback, or audit.
- Enabling unrestricted autonomous self-modification or host control.
- Presenting roadmap items as implemented product capabilities.

## Contributor FAQ

### Where should I start?

Read [Docs/README.md](Docs/README.md), verify repository state, then review the
architecture and development guide for the subsystem you intend to change.

### Which file starts the application?

`main.py` is the process entry point. `narvis.py` contains the application
composition root and dependency registration.

### Can I replace an existing subsystem while adding a provider?

No. Extend the existing provider or registry boundary and preserve the public
facade unless an explicitly approved breaking release says otherwise.

### Do Agent or AI Orchestrator plans execute?

No. They are planning and architecture records. Executable operations require
the existing trusted execution path and explicitly registered dispatch support.

### What must pass before review?

Relevant focused tests, the complete regression suite, documentation checks
applicable to the change, and `git diff --check`. The full Version 1.4 baseline
is 1,052 passing tests.

### May I commit generated or runtime data?

Only when it is an intentional, reviewed part of approved scope. Inspect memory
databases, bytecode, logs, screenshots, and temporary directories before
staging.

## Recovery

If context is lost or work is interrupted, stop mutation and follow
[Docs/CODEX_RECOVERY_PROMPT.md](Docs/CODEX_RECOVERY_PROMPT.md) and
[Docs/RECOVERY_CHECKLIST.md](Docs/RECOVERY_CHECKLIST.md). Git history, source,
and tests take precedence over remembered context or stale documentation.

## License

NARVIS is available under the [MIT License](LICENSE).
