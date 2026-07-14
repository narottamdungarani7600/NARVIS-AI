# NARVIS Software Architecture

## 1. Vision

NARVIS (Next-Generation AI Virtual Intelligent Response System) is a modular, extensible, and professional AI operating system. The current codebase combines an application runtime for AI reasoning, conversation management, memory, voice and vision foundations, internet services, desktop automation, a dashboard, plugins, and events with a separately composable trusted execution boundary.

The long-term vision is to build a resilient and scalable AI ecosystem where each subsystem can evolve independently without compromising the integrity of the whole system.

---

## 2. Project Goals

The primary goals of NARVIS are:

- Maintain a scalable and modular architecture for an intelligent assistant runtime.
- Establish a clean separation of responsibilities across subsystems.
- Provide extensibility for voice, vision, memory, skills, automation, and internet integrations.
- Maintain high standards of readability, maintainability, and testability.
- Prepare the system for future cloud deployment, distributed processing, and advanced AI capabilities.
- Ensure the architecture remains technology-agnostic at the core while supporting practical integrations.
- Preserve fail-closed permission, risk, approval, verification, rollback, and audit boundaries around trusted execution.

---

## 3. High-Level Architecture

NARVIS uses a layered architecture centered on the Core foundation. `NARVISApplication` in `narvis.py` composes the main assistant runtime; `Core/execution/` provides a separate execution package that must be assembled with explicit dispatcher interfaces when used.

### Architectural Layers

1. Presentation and input layer
   - Dashboard UI, text requests, voice input/output, vision capture, and other interaction surfaces.
2. Application and orchestration layer
   - AI Brain, intent routing, skills, command pipelines, workflow services, and response coordination.
3. Domain service layer
   - Memory, internet, voice, vision, computer control, automation, and observe-only evolution services.
4. Trusted execution layer
   - Typed requests, permissions, risk analysis, policy and approval decisions, optional dispatch, verification, rollback simulation, and auditing.
5. Infrastructure layer
   - Dependency injection, lifecycle management, logging, configuration, health checks, EventBus, storage, plugin registration, and system coordination.

### Core Design Principles

- Separation of concerns across modules.
- Dependency inversion through abstractions and interfaces.
- Synchronous event-driven communication between decoupled in-process services.
- Flexible plugin-based extension points.
- Deterministic lifecycle management for system components.
- Explicit, fail-closed trust boundaries for executable operations.

---

## 4. Module Responsibilities

Each major module has a distinct responsibility.

### Core

Responsible for the foundational architecture of the system, including:
- configuration management
- logging abstractions
- lifecycle management
- engine contracts
- system coordination
- startup orchestration
- dependency injection and EventBus services
- plugin registration and health reporting
- trusted execution contracts and services

### AI

Responsible for Brain orchestration, intent classification and routing, provider adapters, prompts, response construction, conversation sessions, and contextual reasoning without embedding infrastructure logic in the reasoning layer.

### Voice

Responsible for audio capture, speech-to-text, text-to-speech, wake-word detection, voice sessions, and health reporting through stable, replaceable interfaces.

### Vision

Responsible for camera and screenshot capture, image loading and preprocessing, OCR, object, face, barcode, and QR detection, and composable image analysis.

### Memory

Responsible for short-term, long-term, session, profile, semantic, and persistent memory; contextual recovery; search; ranking; recall; forgetting; and context summaries.

### Skills

Responsible for organizing reusable capabilities that the assistant can invoke based on context or user intent.

### Internet

Responsible for safe search, grounded research, HTTP access, news, weather, Wikipedia, caching, diagnostics, and replaceable remote providers.

### Automation

Responsible for action queues, scheduling, workflows, and workspace-scoped file and folder automation.

### Computer

Responsible for application resolution, universal target opening, windows, keyboard, mouse, clipboard, screenshots, and desktop-control facades.

### Dashboard

Responsible for the runtime UI, module health, logs, metrics, insights, tests, and lifecycle controls.

### Evolution

Responsible for observe-only capability inventory, proposal and approval records, planning, verification and recovery records, narrow mutation validation, and deterministic future-action simulations.

### Config

Responsible for centralized configuration models and environment-driven settings.

### Assets

Responsible for storing static resources, manifests, templates, and non-code artifacts.

### Logs

Responsible for runtime diagnostics, structured logs, and operational observability.

### Tests

Responsible for automated validation of modules and integrations.

### Docs

Responsible for technical documents, design notes, and developer guidance.

---

## 5. Folder Responsibilities

The repository structure is intended to reflect architectural boundaries clearly.

- Root: project entry points, setup files, and documentation.
- Core/: reusable infrastructure and architectural contracts.
- Core/execution/: trusted execution models, permissions, risk, policies, approvals, dispatch, verification, rollback, and audit.
- AI/: intelligent reasoning and orchestration components.
- Voice/: audio input/output processing.
- Vision/: image and video perception components.
- Memory/: memory abstractions and persistence layers.
- Skills/: reusable functional capabilities.
- Internet/: external communication and remote resource access.
- Automation/: task execution and process automation.
- Computer/: desktop and application control services.
- Dashboard/: runtime monitoring and control UI.
- Evolution/: observe-only evolution, planning, validation, and simulation services.
- Config/: configuration models and environment definitions.
- Assets/: static files and supportive content.
- Logs/: operational log artifacts and observability outputs.
- Tests/: automated tests and validation assets.
- Docs/: architecture documentation and developer resources.

Every new module should map to one of these responsibilities and avoid mixing concerns.

---

## 6. Voice Pipeline

The voice foundation is composed of independent, replaceable stages:

1. Input Capture
   - `AudioInputService` and microphone adapters collect audio frames.

2. Wake-Word Detection
   - Optional wake-word detectors control when a voice request is accepted.

3. Speech Recognition
   - Pluggable speech-to-text engines convert captured audio to text.

4. Command Processing
   - `VoiceCommandProcessor` forwards recognized text to the configured Brain or command handler.

5. Speech Synthesis
   - Pluggable text-to-speech engines convert generated responses into audio.

6. Session and Runtime Management
   - Voice sessions, queues, state, lifecycle, optional-dependency warnings, and health reports are coordinated by the voice managers and `VoiceRuntimeService`.

Null implementations preserve deterministic startup and testing when devices or optional dependencies are unavailable.

---

## 7. AI Brain Pipeline

The AI Brain is the central request-orchestration layer.

### Current stages

1. Context Intake
   - Gather user input, conversation state, runtime metadata, and memory context.

2. Intent Understanding
   - Classify the request and identify routing signals.

3. Routing and Planning
   - Select a module route and construct observable plan steps.

4. Capability Coordination
   - Invoke matching skills or runtime services, including memory, internet, and desktop capabilities.

5. Provider Generation
   - Build prompts and invoke the configured AI provider or fallback behavior when generation is needed.

6. Result Synthesis
   - Build a typed Brain response, record the turn, update context, and publish Brain lifecycle events.

The Brain depends on protocols and injected services rather than direct infrastructure implementations.

---

## 8. Memory Pipeline

The memory pipeline manages short-term and long-term context across conversation, session, profile, and semantic categories.

### Memory responsibilities:

- Capture session context.
- Store user-related facts and preferences.
- Retrieve relevant prior context.
- Support reasoning over historical interactions.
- Preserve privacy and security boundaries.

### Current stages

1. Capture
2. Normalize
3. Store
4. Retrieve
5. Rank
6. Recall
7. Reason and summarize
8. Invalidate affected retrieval caches

`MemoryIntegrationService` coordinates repository storage, search, ranking, profile facts, conversation recovery, visibility rules, deduplication, confidence scoring, and context summaries. Storage implementations remain isolated behind interfaces so they can evolve independently.

---

## 9. Vision Pipeline

The vision foundation handles visual acquisition and analysis through pluggable services.

### Current stages

1. Image or frame acquisition.
2. Preprocessing and normalization.
3. OCR, object, face, barcode, or QR detection where configured.
4. Composite analysis and context interpretation.
5. Typed result packaging and health reporting.

Camera, screenshot, loader, preprocessor, OCR, and detector implementations are replaceable. Null adapters allow the runtime to operate without requiring every optional backend.

---

## 10. Automation Pipeline

The automation pipeline coordinates typed actions, queues, scheduling, workspace operations, and sequential workflows.

### Current responsibilities

- Trigger actions based on events or commands.
- Execute supported actions and workflows through injected services.
- Monitor task lifecycle.
- Report outcomes and errors.

### Current stages

1. Trigger
2. Validation
3. Execution
4. Supervision
5. Completion reporting

Automation remains a composable subsystem reused by skills and higher-level orchestration. Desktop operations are exposed through the `Computer` facades, while trusted execution uses separate permission and approval boundaries.

---

## 11. Plugin System

NARVIS includes a plugin architecture for modular extension. `PluginLoader` executes registered hooks, while `PluginRegistry` tracks descriptors, load state, counts, and runtime-visible metadata. `ManagedPluginHook` combines hook execution with registry and error tracking.

### Plugin Principles

- Plugins must implement stable interfaces.
- Plugins should be discoverable and registerable at runtime or startup.
- The core system must not depend on specific plugin implementations.
- Plugin failures should be isolated and reported clearly.

### Plugin categories

- Voice providers
- Vision providers
- Memory backends
- Skill modules
- Automation actions
- Internet connectors
- Runtime and cloud integration hooks

Plugins receive the dependency container, EventBus, and logger through the stable hook contract. Plugin failures are surfaced rather than silently changing core behavior.

---

## 12. Event Bus Architecture

The Core `EventBus` connects independent components using named `SystemEvent` values and structured payloads.

### Event Bus Goals

- Decouple producers from consumers.
- Support deterministic synchronous in-process publication.
- Promote modular coordination across services.
- Provide an interface that can be replaced if future scale requires a different transport.

### Event Principles

- Events should represent meaningful state changes or system notifications.
- Consumers should subscribe to specific event types.
- Event payloads should be plain, structured, and easy to validate.
- Event processing should be observable and testable.

The current EventBus is intentionally small and in-process. It does not provide persistence, background delivery, or distributed transport.

---

## 13. Trusted Execution Architecture

`Core/execution/` provides the Phase 8 trusted execution foundation. Every
component is typed, dependency-injected, independently testable, and designed to
fail closed.

### Execution lifecycle

1. `TrustedExecutionGateway` validates the request structure and correlation data.
2. `PermissionEngine` evaluates hierarchical and action-specific permission requirements.
3. `RiskAnalyzer` applies permission, action, metadata, and custom risk rules.
4. `ApprovalManager` applies the configured trust policy and returns an explicit allow, deny, or approval-required decision.
5. `ExecutionDispatcher`, when explicitly injected, routes an approved request to the most specific registered interface.
6. `VerificationEngine` validates completion and expected outcome data.
7. `RollbackManager` builds and simulates typed rollback plans when verification indicates that recovery is required.
8. `AuditLogger` records immutable, timestamped lifecycle entries and can forward them to an optional backend or exporter.
9. Execution events and structured logs expose lifecycle transitions without publishing request parameters.

Without a configured dispatcher, the gateway stops at authorization and reports
a non-executing result. Authorization failures never reach dispatch. Dispatcher,
verification, event-subscriber, audit-backend, and rollback failures are handled
at their trust boundaries so the gateway can return a typed, correlated result.

The trusted execution package is composable infrastructure; host-capable adapters
must be registered explicitly and must not bypass permission, approval,
verification, rollback, or audit controls.

---

## 14. Configuration Management

Configuration management must be centralized, explicit, and environment-aware.

### Requirements

- Support development, testing, and production environments.
- Keep sensitive values outside source control.
- Use typed configuration structures.
- Allow runtime updates where appropriate.
- Support module-specific configuration without creating global coupling.

### Design Approach

- Provide a central configuration model in Core.
- Allow modules to access configuration through shared interfaces.
- Validate configuration values at startup.
- Separate defaults, overrides, and secrets.

---

## 15. Logging System

A professional logging system is essential for maintainability and observability.

### Logging Requirements

- Structured logging with severity levels.
- Modular logger interfaces for dependency injection.
- Consistent formatting and context enrichment.
- Support for development and production output targets.
- Avoid logging sensitive content.

### Logging Strategy

- Core defines logging abstractions.
- Modules use the abstraction rather than direct print statements.
- Logs will support future integration with external monitoring tools.

---

## 16. Error Handling Strategy

NARVIS must adopt a predictable and explicit error handling model.

### Principles

- Fail fast when invalid configuration or missing dependencies are detected.
- Handle errors at the appropriate abstraction boundary.
- Surface clear and meaningful error information.
- Avoid silent failures.
- Ensure the system can recover gracefully where appropriate.

### Error Handling Approach

- Use domain-appropriate exception types.
- Provide logging and diagnostics for failures.
- Ensure higher-level orchestration can respond to downstream errors.
- Preserve system stability even when a subsystem fails.

---

## 17. Security Principles

Security must be designed into the system from the start.

### Core Security Principles

- Never hardcode secrets.
- Keep sensitive configuration isolated from source control.
- Validate all external input.
- Ensure least-privilege access for services and plugins.
- Protect user data and session context.
- Maintain clear trust boundaries between components.
- Route executable requests through typed permission, risk, policy, approval, verification, rollback, and audit services.
- Fail closed when validation or a decision dependency fails.

### Future Security Expansion

- Authentication and authorization layers.
- Secure plugin verification.
- Encrypted storage for sensitive memory content.
- Durable and externally reviewable audit storage for critical actions.

---

## 18. Performance Strategy

Performance should be considered as a design discipline rather than a late-stage optimization.

### Principles

- Favor efficient and simple execution paths.
- Avoid unnecessary network or I/O overhead.
- Keep data movement explicit and controlled.
- Use asynchronous patterns where beneficial.
- Profile critical workflows before optimization.

### Target Areas

- Voice pipeline latency.
- Memory retrieval efficiency.
- Context processing throughput.
- Plugin loading and initialization time.
- Event throughput and handling efficiency.

---

## 19. Future Cloud Integration

The system is designed to support future cloud deployment and distributed operation.

### Planned Integration Directions

- Remote configuration management.
- Cloud-based model or service access.
- Centralized monitoring and observability.
- Distributed event processing.
- Scalable memory and storage layers.
- Multi-instance orchestration.

The architecture will remain modular so that cloud services can be introduced through interfaces rather than rewriting core logic.

---

## 20. Development Roadmap

Version 1.1 Stable completes the planned implementation through Phase 8,
including Phase 8 Sprints 1-3 for the Trusted Execution Gateway.

Completed foundations include Core lifecycle and composition, AI Brain and
conversation, memory, voice, vision, internet, skills, desktop and automation,
dashboard observability, plugins, EventBus coordination, observe-only evolution,
and the trusted execution lifecycle.

Future milestones must be scoped explicitly. Current priorities include
production adapter hardening, broader provider support, stronger voice and
vision backends, continued execution-safety verification, deployment readiness,
and optional cloud integration. Future work must preserve the current fail-closed
trust boundaries.

---

## 21. Coding Standards

All implementation work must follow these standards:

- Use Python best practices.
- Write complete docstrings for public modules, classes, functions, and methods.
- Use type hints throughout the codebase.
- Favor clarity, readability, and maintainability.
- Keep modules small, focused, and reusable.
- Follow clean architecture boundaries.
- Avoid premature optimization.
- Write tests for reusable and critical logic.
- Keep dependencies explicit and minimal.
- Preserve the separation between core architecture and feature implementations.

The project must be developed as a professional engineering system, not as a one-off prototype.
