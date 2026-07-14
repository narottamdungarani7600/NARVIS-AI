# NARVIS AI Operating System

Professional modular AI Operating System written in Python.

## Overview

NARVIS is a modular assistant runtime that combines AI reasoning, conversation,
memory, voice, vision, internet research, desktop automation, and runtime
monitoring in one dependency-injected application. The project also provides a
composable trusted execution foundation for permission-controlled operations.
Independent domain packages are coordinated by a shared Core layer and the
`NARVISApplication` composition root.

NARVIS 1.1 Stable represents the completed implementation through Phase 8,
including all three Trusted Execution Gateway sprints.

## Vision

NARVIS is designed to provide a maintainable foundation for an intelligent
operating environment in which reasoning, perception, memory, tools, and
controlled execution can evolve independently. Its architecture emphasizes
clear trust boundaries, explicit dependencies, testability, observability, and
safe extension through plugins and events.

## Features

- AI Brain
- Conversation Engine
- Memory System
- Voice Foundation
- Vision Foundation
- Internet Layer
- Dashboard
- Trusted Execution Gateway
- Permission Engine
- Risk Analyzer
- Approval Manager
- Execution Dispatcher
- Verification Engine
- Rollback Manager
- Audit Logger
- Plugin Framework
- EventBus
- Dependency Injection

## Current Architecture

NARVIS uses a layered, service-oriented architecture:

1. **Presentation and input** - the dashboard, text input, voice services, and
   vision services provide interaction and perception surfaces.
2. **Intelligence and orchestration** - the AI Brain classifies intent, builds
   context, coordinates skills and providers, and produces responses.
3. **Domain services** - memory, internet, desktop control, automation, skills,
   voice, vision, and evolution services implement focused capabilities.
4. **Trusted execution** - the standalone Core execution package passes typed
   requests through permission, risk, policy, approval, optional dispatch,
   verification, rollback, and audit boundaries. The gateway fails closed and
   dispatches only through explicitly injected interfaces.
5. **Core infrastructure** - configuration, logging, lifecycle management,
   dependency injection, plugins, health checks, and the in-process EventBus
   coordinate the runtime.

`narvis.py` is the application composition root. It builds the dependency
container, registers domain services, wires lifecycle hooks and health checks,
loads managed plugins, and exposes the dashboard runtime.

`Core/execution/` is intentionally composable rather than automatically coupled
to the application composition root. Consumers must explicitly provide any
dispatcher or host-capable interface.

## Module Structure

| Module | Responsibility |
| --- | --- |
| `AI/` | Brain orchestration, intent analysis, routing, prompts, providers, responses, and conversation context |
| `Core/` | Configuration, logging, lifecycle, dependency injection, EventBus, plugins, optimization, and trusted execution |
| `Memory/` | Short-term, long-term, session, profile, semantic, persistent, and context-recovery memory |
| `Voice/` | Audio capture, speech recognition, speech synthesis, wake words, sessions, and runtime health |
| `Vision/` | Camera and screenshot capture, image loading, preprocessing, OCR, detection, and analysis |
| `Internet/` | Safe search, research, HTTP access, news, weather, Wikipedia, and provider abstractions |
| `Skills/` | Skill contracts, registry, execution, built-in skills, memory commands, and desktop commands |
| `Computer/` | Applications, windows, keyboard, mouse, clipboard, screenshots, and universal open resolution |
| `Automation/` | Actions, queues, scheduling, workflows, and workspace-scoped file and folder services |
| `Dashboard/` | Runtime UI, metrics, logs, health status, insights, and lifecycle controls |
| `Evolution/` | Observe-only capability inventory, planning, approval, verification, recovery, and execution simulations |
| `Tests/` | Automated unit and integration coverage |
| `Docs/` | Project state, roadmap, decisions, recovery, and engineering guidance |

## Runtime Components

- `NARVISApplication` composes and controls the complete runtime.
- `NARVISRuntimeEngine` provides the application engine lifecycle.
- `DependencyContainer` registers and resolves services and factories.
- `LifecycleManager` coordinates startup, component initialization, and shutdown.
- `EventBus` publishes synchronous in-process lifecycle and subsystem events.
- `BrainEngine` coordinates intent, context, memory, skills, providers, and
  response generation.
- `MemoryIntegrationService` handles storage, recall, search, profiles,
  conversation recovery, ranking, and context summaries.
- `VoiceRuntimeService` and `VisionService` expose pluggable perception
  foundations and health reporting.
- `InternetService` coordinates safe provider-backed search, research, news,
  weather, Wikipedia, and related internet operations.
- `DashboardModule` presents module health, logs, metrics, runtime insights, and
  lifecycle controls.
- `TrustedExecutionGateway` composes permission, risk, approval, optional
  dispatch, verification, rollback simulation, audit, and execution events.

## Current Capabilities

- Classify and route natural-language requests through the AI Brain.
- Maintain conversation sessions, history, summaries, and contextual follow-ups.
- Store, search, rank, recall, forget, and reason over multiple memory categories.
- Recover conversation and profile context across memory-backed interactions.
- Use configurable AI provider adapters with fallback behavior.
- Register and execute built-in, memory, internet, and desktop skills.
- Perform provider-backed internet research with safe URL handling and grounded
  source records.
- Retrieve news, weather, and Wikipedia results through live provider adapters.
- Capture and process voice and vision data through replaceable services, with
  null implementations when optional dependencies or devices are unavailable.
- Control supported desktop and workspace operations through dedicated facades.
- Inspect runtime health, metrics, logs, skills, plugins, memories, and queued
  actions from the dashboard.
- Validate typed execution requests using permissions, risk rules, policies, and
  approval decisions.
- Route approved requests through injected dispatch interfaces, verify structured
  outcomes, simulate rollback plans when required, and retain audit records.
- Discover and load managed plugins while tracking plugin metadata and load state.
- Coordinate decoupled runtime services through dependency injection and events.

The trusted execution components do not grant unrestricted host access. Without
an explicitly configured dispatcher, authorization remains non-executing;
rollback handling is simulation-oriented and all validation paths fail closed.

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
devices. AI and internet providers may also require provider-specific environment
configuration.

## Running

Launch the NARVIS runtime and dashboard from the repository root:

```powershell
python main.py
```

The application initializes registered services, opens the dashboard, and shuts
the runtime down cleanly when the dashboard closes.

## Testing

Run the complete automated suite from the repository root:

```powershell
python -m unittest discover -s Tests -p "test_*.py"
```

**Current status: 559 automated tests passing.**

## Project Structure

```text
NARVIS/
|-- AI/                       # Brain, intent, providers, and conversation
|-- Automation/               # Scheduling, workflows, and workspace actions
|-- Computer/                 # Desktop and application control services
|-- Config/                   # Configuration package
|-- Core/                     # Runtime infrastructure and trusted execution
|   `-- execution/            # Permission-to-audit execution pipeline
|-- Dashboard/                # Runtime dashboard and status models
|-- Docs/                     # Project and engineering documentation
|-- Evolution/                # Observe-only evolution and simulations
|-- Internet/                 # Search, research, and internet providers
|-- Memory/                   # Memory stores, retrieval, and integration
|-- Skills/                   # Skill framework and built-in capabilities
|-- Tests/                    # Automated tests
|-- Vision/                   # Vision foundation and adapters
|-- Voice/                    # Voice foundation and adapters
|-- main.py                   # Application entry point
|-- narvis.py                 # Application composition root
|-- README.md
`-- requirements.txt
```

## Development Workflow

1. Base work on `develop-v1.1` and create a focused feature or documentation
   branch.
2. Follow [PROJECT_DEVELOPMENT_GUIDE.md](PROJECT_DEVELOPMENT_GUIDE.md) and
   [SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md).
3. Keep dependencies explicit and register runtime services through the shared
   dependency container.
4. Preserve the trusted execution, approval, verification, rollback, and audit
   boundaries for any execution-related work.
5. Add or update deterministic tests for behavioral changes.
6. Run the complete test suite and update relevant documentation before review.

Contribution expectations are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Version Information

- **Current version:** 1.1 Stable
- **Development branch:** `develop-v1.1`
- **Developer:** Narottam
- **Release status:** Phases 1 through 8 complete, including Phase 8 Sprints 1-3
- **Test status:** 559 automated tests passing

## Roadmap

Version 1.1 Stable is the current release milestone. Future work will build on
the Phase 8 trusted execution foundation through explicitly scoped milestones,
with priorities including production adapter hardening, broader provider
integration, stronger voice and vision backends, continued safety verification,
and deployment readiness. Existing fail-closed execution and approval boundaries
must remain intact as capabilities expand.

## License

NARVIS is licensed under the [MIT License](LICENSE).
