# NARVIS Software Architecture

- **Architecture baseline:** Version 1.2 Beta (In Development)
- **Latest stable baseline:** Version 1.1 Stable
- **Completed project phases:** 1 through 10

## 1. Vision

NARVIS (Next-Generation AI Virtual Intelligent Response System) is a modular,
extensible AI operating system and assistant runtime. The current codebase
combines AI reasoning, conversation management, memory, voice and vision
foundations, internet services, skills, planning-only agents, computer and
desktop integration, automation, dashboard observability, plugins, events, and
a separately composable trusted execution boundary.

The long-term vision is a resilient AI ecosystem in which each subsystem can
evolve independently without compromising system integrity, backward
compatibility, or explicit execution controls.

---

## 2. Project Goals

The primary goals of NARVIS are:

- Maintain a scalable and modular architecture for an intelligent assistant
  runtime.
- Establish clear ownership and separation of responsibilities across
  subsystems.
- Keep AI, memory, voice, vision, internet, skills, agents, computer, desktop,
  automation, and infrastructure services replaceable behind stable contracts.
- Maintain high standards of readability, maintainability, observability, and
  testability.
- Preserve all established Version 1.1 APIs and behavior during Version 1.2
  development.
- Prepare the system for future providers, production adapters, cloud
  deployment, and distributed processing.
- Preserve fail-closed permission, risk, approval, verification, rollback, and
  audit boundaries around trusted execution.

---

## 3. High-Level Architecture

NARVIS uses a layered architecture centered on Core infrastructure.
`NARVISApplication` in `narvis.py` composes the established assistant runtime.
The Phase 9 Skill and Agent frameworks and Phase 10 Computer and Desktop
frameworks add independently testable, provider-oriented foundations without
removing legacy APIs. `Core/execution/` remains a separate trusted execution
package that requires explicitly injected dispatch interfaces.

### Architectural Layers

1. **Presentation and perception**
   - Dashboard UI, text requests, voice input/output, and vision capture.
2. **Intelligence and orchestration**
   - AI Brain, intent routing, context construction, provider selection, and
     response coordination.
3. **Capability and planning**
   - Typed skill discovery, matching, resolution, loading, agent planning, and
     workflow validation.
4. **Domain and integration services**
   - Memory, internet, automation, computer information, legacy computer
     controls, desktop inspection, and observe-only evolution services.
5. **Trusted execution**
   - Typed requests, permissions, risk analysis, policy and approval decisions,
     optional dispatch, verification, rollback simulation, and auditing.
6. **Core infrastructure**
   - Dependency injection, lifecycle management, configuration, logging, health
     checks, EventBus, plugins, storage, and system coordination.

### Core Design Principles

- Separation of concerns across packages.
- Dependency inversion through protocols, abstract providers, and injected
  services.
- Deterministic, synchronous event-driven coordination between in-process
  services.
- Extension through skills, providers, plugins, and registered interfaces.
- Explicit lifecycle, health, and validation boundaries.
- Planning remains separate from execution.
- Executable operations remain behind fail-closed trust controls.
- New foundations coexist with legacy APIs to maintain backward compatibility.

---

## 4. Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `AI/` | Brain orchestration, intent classification, routing, prompts, provider adapters, responses, conversations, and contextual reasoning |
| `Memory/` | Short-term, long-term, session, profile, semantic, persistent, recovery, search, ranking, recall, and context-summary services |
| `Voice/` | Audio capture, speech recognition, speech synthesis, wake words, sessions, replaceable engines, and health reporting |
| `Vision/` | Camera and screenshot capture, image loading, preprocessing, OCR, detection, analysis, and health reporting |
| `Internet/` | Safe search, grounded research, HTTP access, downloads, news, weather, Wikipedia, YouTube, caching, diagnostics, and remote-provider abstractions |
| `Skills/` | Existing runtime skills and desktop or memory commands plus the typed Phase 9 skill lifecycle, discovery, matching, and resolution framework |
| `Agents/` | Planning context, dependency-aware task planning, typed plans and workflows, validation, result packaging, logging, and planning events |
| `Computer/core/` | Computer provider contracts, registry, lifecycle manager, capability discovery, health reporting, typed models, and errors |
| `Computer/services/` | Provider-backed, read-only application, filesystem, process, and clipboard information services |
| `Computer/desktop/` | Interface-only display, window, mouse, and keyboard inspection contracts and typed state models |
| Legacy `Computer/` modules | Backward-compatible application resolution, universal open, windows, keyboard, mouse, clipboard, screenshots, and desktop-control facades |
| `Automation/` | Actions, task queues, scheduling, workflows, input abstractions, and workspace-scoped file and folder services |
| `Dashboard/` | Runtime UI, module health, logs, system metrics, insights, module testing, and lifecycle controls |
| `Core/execution/` | Trusted request validation, permission, risk, policy, approval, dispatch, verification, rollback, audit, and lifecycle events |
| `Core/plugins.py` and `Core/system.py` | Plugin descriptors, registry, managed hooks, loader, state tracking, and runtime-visible metadata |
| `Config/` and `Core/config.py` | Project settings, typed runtime configuration, defaults, overrides, and validation |
| `Core/logger.py` and `Logs/` | Logging abstractions, structured context, severity handling, and runtime diagnostics |
| `Core/system.py` | Dependency container, EventBus, health checks, component coordination, and core plugin loading |
| `Core/startup.py` and `Core/engine.py` | Startup hooks, runtime lifecycle, engine contracts, and application coordination |
| `Evolution/` | Observe-only capability discovery, proposals, approvals, planning, verification, recovery, guarded mutation models, and simulations |
| `Tests/` | Automated unit and integration validation across the architecture |
| `Docs/` | Project state, roadmap, design decisions, recovery notes, and engineering guidance |

---

## 5. Dependency Injection and Runtime Composition

Dependency injection is the primary composition mechanism for the established
runtime.

- `NARVISApplication` is the composition root.
- `DependencyContainer` registers shared values and factories and resolves
  dependencies by stable names.
- Runtime services receive dependencies through constructors or explicit
  registration rather than hidden global access.
- Lifecycle and startup coordinators order initialization and shutdown.
- Health checks report subsystem readiness without coupling the Dashboard to
  concrete implementations.
- Plugins receive the container, EventBus, and logger through managed hooks.
- Trusted execution dispatchers and host-capable providers must be supplied
  explicitly.

The Phase 9 and Phase 10 foundations accept logger and event-publisher contracts
without requiring the application composition root. This keeps them reusable
and testable while they are integrated incrementally.

---

## 6. AI Architecture

The AI Brain is the central request-orchestration layer.

### Request Pipeline

1. Gather user input, conversation state, runtime metadata, and relevant memory.
2. Classify intent and identify routing signals.
3. Select a route and construct observable plan metadata.
4. Coordinate an existing skill or domain service when one matches.
5. Build a prompt and invoke the configured AI provider or deterministic
   fallback when generation is needed.
6. Construct a typed response, record the turn, update context, and publish
   lifecycle events.

The Brain depends on injected protocols and services rather than embedding
computer, internet, memory, or provider implementations.

---

## 7. Memory Architecture

The Memory subsystem manages short-term and long-term context across
conversation, session, profile, semantic, and persistent categories.

### Memory Pipeline

1. Capture and normalize information.
2. Apply category, visibility, confidence, and deduplication rules.
3. Store through a repository abstraction.
4. Search and retrieve relevant records.
5. Rank candidates and apply visibility rules.
6. Recall, reason, and create context summaries.
7. Invalidate affected retrieval caches.

`MemoryIntegrationService` coordinates storage, search, ranking, profile facts,
conversation recovery, recall, forgetting, and context summaries. Storage
implementations remain isolated behind interfaces.

---

## 8. Voice Architecture

The Voice foundation is composed of replaceable stages:

1. Audio input and microphone adapters capture frames.
2. Optional wake-word detectors decide when a request is accepted.
3. Pluggable speech-to-text engines produce recognized text.
4. `VoiceCommandProcessor` forwards text to the configured Brain or handler.
5. Pluggable text-to-speech engines synthesize responses.
6. Voice managers and `VoiceRuntimeService` coordinate sessions, queues,
   lifecycle, optional-dependency warnings, and health.

Null implementations preserve deterministic startup and testing when devices or
optional dependencies are unavailable.

---

## 9. Vision Architecture

The Vision foundation handles visual acquisition and analysis through pluggable
services:

1. Acquire a camera frame, screenshot, or image.
2. Load, preprocess, and normalize the input.
3. Apply OCR, object, face, barcode, or QR detection when configured.
4. Compose analysis and contextual interpretation.
5. Return typed results and health information.

Camera, screenshot, loader, preprocessor, OCR, and detector implementations are
replaceable. Null adapters allow the runtime to operate without every optional
backend.

---

## 10. Internet Architecture

`InternetService` coordinates provider-backed internet features:

- safe URL and request handling
- web search and grounded multi-source research
- news, weather, Wikipedia, YouTube, browser, and download services
- source-aware result records and follow-up context
- caching, diagnostics, provider health, and fallback behavior

Remote access stays behind injected adapters. External input and URLs must be
validated, and provider failures must be converted into structured results or
domain errors.

---

## 11. Skill Framework

The Skills package contains two compatible layers:

- the established `Skills/framework.py` runtime registry, executor, built-in
  skills, memory commands, and desktop command pipeline
- the Phase 9 typed framework under `Skills/core/`

### Typed Skill Lifecycle

1. `SkillDefinition`, `SkillMetadata`, `SkillCapability`, `SkillCategory`, and
   `SkillFactory` define skill identity and construction.
2. `SkillRegistry` registers definitions and enforces deterministic uniqueness.
3. `SkillDiscovery` filters the available catalog by criteria and availability.
4. `CapabilityMatcher` scores and ranks capability candidates.
5. `SkillResolver` resolves requested capabilities, categories, availability,
   and preferences into typed results.
6. `SkillLoader` creates and tracks loaded skill instances.
7. `SkillManager` exposes the complete lifecycle through one facade.

Logging and event publication are optional injected contracts. Existing skill
APIs remain in place for backward compatibility.

---

## 12. Agent Framework

`Agents/core/` is a deterministic planning-only framework:

- `PlanningContext` carries normalized intent and planning inputs.
- `TaskPlanner` uses an injected skill resolver to build ordered `Plan` and
  `PlanStep` records.
- `WorkflowDefinition` and `WorkflowStep` represent reusable workflows.
- `WorkflowValidator` validates identifiers, dependencies, ordering, and graph
  integrity.
- `AgentRuntime` coordinates plan creation, validation, typed
  `PlanningResult` values, logging, and events.

The Agent Framework does not run a plan, invoke an executor, or authorize host
actions. Any future execution integration must pass through explicit execution
contracts and the Trusted Execution Gateway.

---

## 13. Computer Integration Layer

Phase 10 adds a provider-oriented foundation under `Computer/core/`:

- `ComputerProvider` defines lifecycle, health, and capability contracts.
- `ComputerRegistry` owns deterministic provider registration and lookup.
- `ComputerManager` coordinates discovery, initialization, shutdown, health,
  and capabilities.
- Typed models describe provider information, statuses, health, capabilities,
  applications, filesystem entries, processes, and clipboard metadata.
- Domain-specific exceptions define registry, lifecycle, discovery, health, and
  information-service failures.

`Computer/services/` adds read-only services over injected protocols:

- `ApplicationService` discovers registered providers and installed or running
  applications.
- `FileSystemService` validates paths and returns file or directory metadata.
- `ProcessService` enumerates processes and supports typed lookup.
- `ClipboardService` reports availability and reads text or metadata.

The provider-based services do not replace the legacy `Computer/` control
facades. Both layers remain available during Version 1.2 Beta integration.

---

## 14. Desktop Integration Layer

`Computer/desktop/` defines typed inspection interfaces:

- `DisplayManager` enumerates displays and resolves primary or virtual displays.
- `WindowManager` enumerates windows and supports identifier or title lookup.
- `MouseInterface` reports pointer position, button state, and combined pointer
  state.
- `KeyboardInterface` reports keyboard state.
- `DesktopProvider` combines display, window, mouse, and keyboard inspection
  with the Computer provider lifecycle.

Providers are injected and results are validated before being exposed. The
layer is interface-only and does not add a new OS mutation or unrestricted
execution path. Operational legacy desktop features remain separate and
backward compatible.

---

## 15. Automation Architecture

The Automation subsystem coordinates typed actions, queues, scheduling,
workspace operations, and sequential workflows.

### Automation Pipeline

1. Receive a trigger from a command, event, schedule, or caller.
2. Validate the action and its parameters.
3. Route to an injected service.
4. Track task or workflow lifecycle.
5. Report structured completion or failure.

Automation remains composable and is reused by skills and higher-level
orchestration. Automation does not replace trusted permission and approval
boundaries.

---

## 16. Dashboard Architecture

The Dashboard is the runtime presentation and observability surface. It exposes:

- application and module health
- system metrics and logs
- skills, plugins, memories, and queued actions
- runtime insights and status models
- module tests and lifecycle controls

Dashboard code consumes service and health interfaces. It must not bypass
domain services or trusted execution controls.

---

## 17. Plugin Architecture

`PluginDescriptor` and `PluginRegistry` track plugin identity, metadata, load
state, counts, and errors. `ManagedPluginHook` combines hook execution with
registry and failure tracking, while `PluginLoader` coordinates registered
hooks.

### Plugin Principles

- Plugins implement stable and documented interfaces.
- Registration and loading are explicit.
- Core code does not depend on individual plugin implementations.
- Plugin failures are isolated and surfaced.
- Plugins receive dependencies through managed contracts.
- Plugin events and logs must not expose secrets.
- Interface evolution must preserve backward compatibility.

Potential plugin categories include voice and vision providers, memory backends,
skills, automation actions, internet connectors, and runtime integrations.

---

## 18. Event Architecture

The Core `EventBus` connects independent in-process components using named
events and structured payloads.

- Publication is synchronous and deterministic.
- Producers and consumers remain decoupled.
- Subscribers register for specific event names.
- Payloads are plain, structured, testable, and non-sensitive.
- Subscriber failures are handled at the owning subsystem boundary.

The current EventBus is intentionally small and in-process. It does not provide
persistence, background delivery, retries, or distributed transport.

---

## 19. Trusted Execution Architecture

`Core/execution/` provides the Phase 8 Trusted Execution Gateway. Components are
typed, dependency-injected, independently testable, and fail closed.

### Execution Lifecycle

1. `TrustedExecutionGateway` validates the request and correlation data.
2. `PermissionEngine` evaluates hierarchical and action-specific permissions.
3. `RiskAnalyzer` applies permission, action, metadata, and custom risk rules.
4. `ApprovalManager` applies trust policy and returns allow, deny, or
   approval-required.
5. `ExecutionDispatcher`, when explicitly injected, routes an approved request
   to the most specific registered interface.
6. `VerificationEngine` validates completion and expected outcome data.
7. `RollbackManager` builds and simulates typed recovery plans when required.
8. `AuditLogger` records immutable, timestamped lifecycle entries and may
   forward them to an optional backend or exporter.
9. Execution events and structured logs expose transitions without publishing
   request parameters.

Without a configured dispatcher, the gateway stops at authorization and returns
a non-executing result. Authorization failures never reach dispatch. Failures
from dispatchers, verification, event subscribers, audit backends, and rollback
providers are contained at their trust boundaries.

Host-capable adapters must be registered explicitly and must not bypass
permission, approval, verification, rollback, or audit controls.

---

## 20. Configuration Management

Configuration is centralized, explicit, and environment-aware.

- `Core/config.py` defines runtime configuration structures and loading.
- `Config/` contains project configuration and defaults.
- Values are validated during startup.
- Defaults, overrides, environment values, and secrets remain distinct.
- Modules consume injected configuration rather than reading unrelated global
  state.
- Sensitive values remain outside source control.

---

## 21. Logging System

Core logging provides a shared abstraction for structured, contextual
diagnostics.

- Use consistent severity levels and formatting.
- Enrich messages with safe subsystem context.
- Inject loggers into services and frameworks.
- Avoid direct prints in reusable modules.
- Do not record secrets, request parameters, or sensitive user data.
- Keep development and future production output targets replaceable.

The `Logs/` directory is reserved for runtime diagnostic artifacts and is not a
substitute for the logging abstraction.

---

## 22. Error Handling Strategy

- Fail fast on invalid configuration, models, or missing required dependencies.
- Use domain-appropriate exception types.
- Handle errors at the owning abstraction or trust boundary.
- Surface clear typed results or meaningful exceptions.
- Log diagnostic context without sensitive data.
- Avoid silent failures and undefined behavior.
- Preserve system stability when an optional provider or subsystem fails.

---

## 23. Security Principles

- Never hardcode secrets.
- Validate all external input and provider results.
- Use least-privilege services and explicit provider registration.
- Protect user data, session context, and memory visibility.
- Keep planning separate from execution.
- Route executable requests through permission, risk, policy, approval,
  verification, rollback, and audit services.
- Fail closed when validation or authorization dependencies fail.
- Treat simulated rollback or execution results as non-mutating unless an
  explicitly authorized adapter reports otherwise.

Future security work includes authentication, secure plugin verification,
encrypted sensitive storage, and durable externally reviewable audit storage.

---

## 24. Performance Strategy

- Favor simple, deterministic paths.
- Avoid unnecessary network, disk, and provider calls.
- Keep data movement and caches explicit.
- Use asynchronous patterns only where they materially improve the design.
- Profile before optimizing.
- Preserve testability while improving voice latency, memory retrieval, skill
  matching, provider discovery, plugin loading, and event throughput.

---

## 25. Future Cloud Integration

The architecture can support future remote configuration, model access,
centralized observability, distributed events, scalable memory, and
multi-instance orchestration. Cloud services must be introduced through
interfaces and providers rather than by rewriting domain logic or weakening
local trust boundaries.

---

## 26. Development Roadmap

- **Phases 1-8 - Complete:** Version 1.1 Stable foundation, including Core
  composition, AI, memory, voice, vision, internet, automation, dashboard,
  plugins, events, evolution foundations, and the Trusted Execution Gateway.
- **Phase 9 - Complete:** Skill Framework foundation, discovery and resolution,
  and planning-only Agent Framework.
- **Phase 10 - Complete:** Computer provider foundation, read-only computer
  information services, and Desktop Integration inspection interfaces.
- **Version 1.2 Beta preparation - In development:** integration review,
  documentation synchronization, backward-compatibility verification, and beta
  validation.
- **Future milestones:** production adapter hardening, broader providers,
  stronger voice and vision backends, continued safety verification, deployment
  readiness, and optional cloud integration.

Observe-only Self-Evolution history through its Phase 10 simulation framework
remains documented under `Docs/`. That roadmap is separate from the Version 1.2
Skill, Agent, Computer, and Desktop project phases and does not authorize host
mutation.

---

## 27. Coding Standards

- Use Python 3.10+ best practices.
- Write complete docstrings for public modules, classes, functions, and methods.
- Use type hints throughout the codebase.
- Favor clarity, readability, and maintainability.
- Keep modules focused, reusable, and cohesive.
- Preserve clean architecture and trust boundaries.
- Keep dependencies explicit and minimal.
- Add deterministic tests for reusable and critical behavior.
- Preserve public APIs and established behavior unless an explicitly approved
  breaking release says otherwise.

NARVIS must be developed as a professional engineering system, not as a
one-off prototype.
