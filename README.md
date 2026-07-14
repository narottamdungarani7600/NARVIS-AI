# NARVIS AI Operating System

Professional modular AI Operating System written in Python.

- **Current development version:** 1.2 Beta (In Development)
- **Latest stable version:** 1.1 Stable
- **Development branch:** `develop-v1.1`
- **Automated test status:** 687 tests passing

## Overview

NARVIS is a modular assistant runtime that combines AI reasoning, conversation,
memory, voice, vision, internet research, skills, agent planning, computer and
desktop integration, automation, and runtime monitoring in one extensible
system. Independent domain packages are coordinated through explicit contracts,
dependency injection, synchronous events, and the `NARVISApplication`
composition root.

Version 1.2 Beta preparation builds on the Version 1.1 Stable foundation. Phase
9 added the typed Skill Framework and planning-only Agent Framework. Phase 10
added the provider-based Computer Integration Layer and interface-only Desktop
Integration Layer. The existing Trusted Execution Gateway remains the
permission-controlled boundary for executable operations.

## Vision

NARVIS provides a maintainable foundation for an intelligent operating
environment in which reasoning, perception, memory, capabilities, planning, and
controlled execution can evolve independently. The architecture emphasizes
stable interfaces, complete backward compatibility, explicit trust boundaries,
observability, testability, and safe extension through skills, providers,
plugins, and events.

## Current Architecture

NARVIS uses a layered, service-oriented architecture:

1. **Presentation and perception** - the dashboard, text interface, voice
   services, and vision services provide interaction and perception surfaces.
2. **Intelligence and orchestration** - the AI Brain classifies intent, builds
   context, routes requests, coordinates providers, and constructs responses.
3. **Capabilities and planning** - the Skill Framework discovers, matches,
   resolves, loads, and manages typed skills; the Agent Framework converts
   intent into validated dependency-aware plans without executing them.
4. **Domain and integration services** - memory, internet, automation, computer
   information services, legacy computer controls, and desktop inspection
   interfaces provide focused capabilities behind stable contracts.
5. **Trusted execution** - typed requests pass through permission, risk, policy,
   approval, optional dispatch, verification, rollback, and audit boundaries.
6. **Core infrastructure** - configuration, logging, lifecycle management,
   dependency injection, plugins, health checks, and the in-process EventBus
   coordinate the runtime.

`narvis.py` is the application composition root for the established assistant
runtime. The Phase 9 and Phase 10 frameworks are independently testable,
provider-oriented foundations that coexist with the existing Skills and
Computer APIs to preserve backward compatibility.

`Core/execution/` remains intentionally composable. It is not an unrestricted
host bridge: consumers must explicitly provide dispatcher interfaces, and
authorization paths fail closed.

## Major Subsystems

| Subsystem | Responsibility |
| --- | --- |
| `AI/` | Brain orchestration, intent analysis, routing, prompts, providers, responses, and conversation context |
| `Memory/` | Short-term, long-term, session, profile, semantic, persistent, and context-recovery memory |
| `Voice/` | Audio capture, speech recognition, synthesis, wake words, sessions, and health reporting |
| `Vision/` | Camera and screenshot capture, image processing, OCR, detection, and analysis |
| `Internet/` | Safe search, research, HTTP access, news, weather, Wikipedia, and provider abstractions |
| `Skills/` | Legacy runtime skills plus typed registration, discovery, capability matching, resolution, and lifecycle management |
| `Agents/` | Planning context, task planning, workflow validation, plan models, and planning-only runtime coordination |
| `Computer/core/` | Provider registry, lifecycle management, capability discovery, health, and typed computer models |
| `Computer/services/` | Provider-backed application, filesystem, process, and clipboard information services |
| `Computer/desktop/` | Interface-only display, window, mouse, and keyboard inspection layer |
| `Computer/` legacy modules | Backward-compatible applications, windows, keyboard, mouse, clipboard, screenshots, and universal-open controls |
| `Automation/` | Actions, queues, scheduling, workflows, and workspace-scoped file and folder services |
| `Dashboard/` | Runtime UI, metrics, logs, health status, insights, tests, and lifecycle controls |
| `Core/execution/` | Trusted permission-to-audit execution pipeline |
| `Core/plugins.py` and `Core/system.py` | Plugin descriptors, registry, managed hooks, loading, and runtime metadata |
| `Core/config.py` and `Config/` | Central configuration models, defaults, and project settings |
| `Core/logger.py` and `Logs/` | Structured logging abstractions and runtime diagnostics |
| `Core/system.py` | Dependency container, EventBus, lifecycle coordination, health checks, and plugin loader |
| `Evolution/` | Observe-only discovery, planning, approval, verification, recovery, validation, and simulation services |

## Skill Framework

The Phase 9 Skill Framework under `Skills/core/` adds typed, composable skill
management without removing the established `Skills/framework.py` API.

- `SkillDefinition`, `SkillMetadata`, `SkillCapability`, and related models
  describe skill identity, categories, factories, availability, and capabilities.
- `SkillRegistry` and `SkillLoader` manage registration and loaded instances
  with explicit duplicate, missing, load, and unload errors.
- `SkillDiscovery` filters the available catalog.
- `CapabilityMatcher` ranks candidates against requested capabilities.
- `SkillResolver` produces deterministic resolution results.
- `SkillManager` provides one facade for registration, discovery, matching,
  resolution, loading, and unloading.
- Optional logger and event-publisher contracts keep the framework observable
  without coupling it to a specific runtime.

## Agent Framework

The Phase 9 planning-only Agent Framework under `Agents/core/` converts intent
and context into deterministic plans:

- `PlanningContext` carries normalized planning inputs.
- `TaskPlanner` resolves skills and creates ordered `PlanStep` records.
- `WorkflowValidator` validates step identifiers, dependencies, ordering, and
  workflow structure.
- `AgentRuntime` coordinates planning, validation, result packaging, logging,
  and events.

The Agent Framework does not execute plan steps. Execution remains separated
from planning and must respect the Trusted Execution Gateway and existing
runtime boundaries.

## Computer Integration Layer

Phase 10 introduced a provider-based Computer Integration Layer:

- `ComputerRegistry` stores typed `ComputerProvider` implementations.
- `ComputerManager` coordinates provider registration, initialization,
  shutdown, health checks, and capability discovery.
- `ApplicationService` discovers registered providers plus installed and
  running applications through injected protocols.
- `FileSystemService` exposes path validation, metadata, and directory or file
  listing through an injected provider.
- `ProcessService` supports process enumeration and typed lookup.
- `ClipboardService` exposes availability, text reads, and metadata.

The new information services are provider-backed and read-only by contract.
Legacy `Computer/` control modules remain available for existing callers.

## Desktop Integration Layer

`Computer/desktop/` provides typed desktop inspection contracts:

- `DisplayManager` enumerates displays and resolves primary or virtual displays.
- `WindowManager` enumerates and looks up typed window metadata.
- `MouseInterface` reports pointer position, button state, and combined pointer
  state.
- `KeyboardInterface` reports keyboard state.
- `DesktopProvider` combines the inspection protocols with the Computer
  provider lifecycle.

This layer defines interfaces and validation boundaries; it does not add a new
unrestricted OS execution path.

## Trusted Execution Gateway

`Core/execution/` implements the Phase 8 Trusted Execution Gateway:

1. `TrustedExecutionGateway` validates typed requests and correlation data.
2. `PermissionEngine` evaluates hierarchical and action-specific permissions.
3. `RiskAnalyzer` applies risk rules.
4. `ApprovalManager` applies trust policy and returns allow, deny, or
   approval-required.
5. `ExecutionDispatcher` optionally routes approved requests through explicitly
   registered interfaces.
6. `VerificationEngine` validates completion and expected outcomes.
7. `RollbackManager` creates typed, simulation-oriented recovery plans.
8. `AuditLogger` records immutable lifecycle entries.

Without a configured dispatcher, authorization remains non-executing.
Dispatcher, verification, audit, event, and rollback failures are contained at
their trust boundaries.

## Installation

NARVIS requires Python 3.10 or newer.

```powershell
git checkout develop-v1.1
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Voice features depend on the optional audio stack and available input/output
devices. AI and internet providers may also require provider-specific
environment configuration.

## Running

Launch the NARVIS runtime and dashboard from the repository root:

```powershell
python main.py
```

The application initializes registered services, opens the dashboard, and
shuts the runtime down cleanly when the dashboard closes.

## Testing

Run the complete automated suite from the repository root:

```powershell
python -m unittest discover -s Tests -p "test_*.py"
```

**Current status: 687 automated tests passing.**

The Version 1.1 Stable checkpoint contained 559 passing tests. Phase 9 and Phase
10 increased the suite by 128 tests across skill registration and discovery,
agent planning, computer provider services, and desktop integration.

## Repository Structure

```text
NARVIS/
|-- Agents/
|   `-- core/                  # Planning-only agent framework
|-- AI/                       # Brain, intent, providers, and conversation
|-- Automation/               # Scheduling, workflows, and workspace actions
|-- Computer/
|   |-- core/                 # Provider lifecycle and capability foundation
|   |-- services/             # Read-only computer information services
|   `-- desktop/              # Desktop inspection interfaces and models
|-- Config/                   # Project configuration
|-- Core/
|   `-- execution/            # Permission-to-audit execution pipeline
|-- Dashboard/                # Runtime dashboard and status models
|-- Docs/                     # Project state and engineering documentation
|-- Evolution/                # Observe-only evolution and simulations
|-- Internet/                 # Search, research, and internet providers
|-- Memory/                   # Memory stores, retrieval, and integration
|-- Skills/
|   `-- core/                 # Typed skill discovery and lifecycle framework
|-- Tests/                    # Automated unit and integration tests
|-- Vision/                   # Vision foundation and adapters
|-- Voice/                    # Voice foundation and adapters
|-- main.py                   # Application entry point
|-- narvis.py                 # Application composition root
|-- README.md
|-- CHANGELOG.md
|-- SOFTWARE_ARCHITECTURE.md
`-- PROJECT_DEVELOPMENT_GUIDE.md
```

## Development Workflow

Development follows an architecture-first process: architecture design, focused
Codex implementation, architecture review, focused and full-suite testing, Git
commit, push, and release tagging. See
[PROJECT_DEVELOPMENT_GUIDE.md](PROJECT_DEVELOPMENT_GUIDE.md) for the complete
workflow and [SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md) for subsystem
contracts.

Contributions must preserve existing public behavior and established trust
boundaries. Contribution expectations are documented in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Version Information

- **Current version:** 1.2 Beta (In Development)
- **Latest stable version:** 1.1 Stable
- **Development branch:** `develop-v1.1`
- **Developer:** Narottam
- **Release status:** Phases 1 through 10 complete; beta integration and
  documentation synchronization are in progress
- **Test status:** 687 automated tests passing

## Current Roadmap

- **Phases 1-8 - Complete:** Version 1.1 Stable foundation, culminating in the
  Trusted Execution Gateway.
- **Phase 9 - Complete:** typed Skill Framework, skill discovery and capability
  resolution, and planning-only Agent Framework.
- **Phase 10 - Complete:** Computer provider foundation, read-only information
  services, and Desktop Integration inspection interfaces.
- **Version 1.2 Beta preparation - In progress:** architecture integration,
  documentation synchronization, compatibility review, and beta validation.
- **Next:** production provider and adapter hardening, broader AI, voice, vision,
  and internet integration, continued execution-safety verification, deployment
  readiness, and explicitly scoped future milestones.

Future work must preserve backward compatibility and the fail-closed permission,
approval, verification, rollback, and audit boundaries.

## License

NARVIS is licensed under the [MIT License](LICENSE).
