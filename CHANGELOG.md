# Changelog

All notable changes to NARVIS will be documented in this file.

## [Unreleased]

### Version 1.5 - Sprint 6: Runtime Configuration Registry

- Added an immutable Runtime Configuration Registry with versioned defaults,
  recursively frozen JSON-safe values, deterministic key ordering, and
  non-mutating copy-on-write updates.
- Added content-addressed configuration identifiers, deterministic hashing,
  compact JSON serialization, integrity-checked deserialization, read-only
  exports, and detached mutable-copy safety.
- Added configuration and schema version validation, schema compatibility
  reports, deterministic configuration comparisons, and aggregate summary
  metadata covering categories, defaults, and overrides.
- Extended the Runtime Metadata Catalog with configuration-registry,
  configuration-schema, and configuration-compatibility versions.
- Embedded one same-timestamp configuration snapshot across Runtime
  Diagnostics, Runtime State, and Runtime Observability; advertised registry
  availability through the Capability Manifest, Runtime Feature Registry,
  Dependency Graph, and Service Registry metadata surfaces.
- Registered the passive configuration registry through the existing DI
  container and exposed application accessors without applying settings or
  adding a lifecycle component or EventBus event path.
- Preserved BrainEngine, provider and AI execution, networking, Conversation,
  Trusted Execution, permissions, approvals, rollback, lifecycle ordering,
  EventBus flow, and all Version 1.4 and Sprint 1-5 behavior.
- Advanced application build metadata to `v1.5-s6` and increased the verified
  full-suite baseline from 1,090 to 1,098 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

### Version 1.5 - Sprint 5: Runtime Metadata and Version Catalog

- Added an immutable Runtime Metadata Catalog describing runtime,
  architecture, schema, repository, compatibility, Feature Registry,
  Capability Manifest, Dependency Graph, Runtime State, Observability, and
  Diagnostics versions.
- Added deterministic content hashes, timestamp-aware snapshot identifiers,
  semantic version validation, compatibility-range verification, and
  component-level snapshot comparison reports.
- Added deeply immutable deterministic exports, compact JSON serialization,
  integrity-checked deserialization, and detached mutable-copy safety.
- Embedded one same-timestamp metadata snapshot across Runtime Diagnostics,
  Runtime State, Runtime Observability, the Capability Manifest, and the
  Runtime Feature Registry.
- Registered the passive catalog through the existing DI container and exposed
  application accessors without adding a lifecycle component or changing
  startup, shutdown, or EventBus ordering.
- Centralized immutable component-version constants used by the Feature
  Registry, Capability Manifest, Dependency Graph, Runtime State,
  Observability, Diagnostics, and Service Registry modules.
- Preserved BrainEngine, provider and AI execution, networking, Trusted
  Execution, permission, approval, rollback, and all Version 1.4 and Sprint
  1-4 behavior.
- Advanced application build metadata to `v1.5-s5` and increased the verified
  full-suite baseline from 1,082 to 1,090 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

### Version 1.5 — Sprint 4: Runtime Observability and Snapshot Engine

- Added an immutable Runtime Snapshot Engine with schema versioning,
  content-addressed snapshot identifiers, capture metadata, timestamps, and
  deterministic same-source capture semantics.
- Added runtime overview, registered-service, registered-feature, capability,
  dependency, readiness, and health summaries in one aggregate observability
  report.
- Added deeply immutable deterministic mapping exports containing feature,
  capability, cycle-free diagnostics, dependency, service, state, and
  aggregate observability snapshots.
- Added deterministic snapshot comparison reports covering schema
  compatibility, content equality, timestamp-only changes, changed sections,
  added or removed services and features, readiness, and health changes.
- Embedded same-timestamp runtime snapshots and observability reports into
  Runtime Diagnostics and advertised snapshot availability through the
  Capability Manifest and Runtime Feature Registry.
- Registered the passive snapshot engine through the existing DI container
  without adding a lifecycle component or changing startup, shutdown, or
  EventBus ordering.
- Preserved BrainEngine, provider and AI execution, networking, Trusted
  Execution, Safe Execution, and all Version 1.4 and Sprint 1–3 behavior.
- Advanced application build metadata to `v1.5-s4` and increased the verified
  full-suite baseline from 1,075 to 1,082 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

### Version 1.5 — Sprint 3: Runtime State and Readiness Engine

- Added an immutable Runtime State Engine that reduces same-timestamp Runtime
  Service Registry, Capability Manifest, Feature Registry, Dependency Graph,
  lifecycle, diagnostics-health, and service-health metadata into deterministic
  runtime state.
- Added `READY`, `PARTIAL`, `NOT_READY`, and `UNKNOWN` aggregate and per-feature
  readiness, including dependency-aware propagation from the existing graph.
- Added immutable runtime state snapshots, readiness summaries, dependency
  impact summaries, compatibility summaries, and combined health summaries.
- Embedded the state snapshot and all derived reports into Runtime Diagnostics
  while preserving one shared capture timestamp and metadata-only calculation.
- Advertised Runtime State Engine availability through the Capability Manifest
  and built-in Runtime Feature Registry catalogue.
- Registered the passive state engine through the existing DI container without
  adding a lifecycle component, changing startup or shutdown order, or adding
  EventBus event paths.
- Preserved BrainEngine, provider and AI execution, networking, Trusted
  Execution, Safe Execution, and all Version 1.4 and Sprint 1–2 behavior.
- Advanced application build metadata to `v1.5-s3` and increased the verified
  full-suite baseline from 1,068 to 1,075 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

### Version 1.5 — Sprint 2: Runtime Dependency Graph and Relationships

- Extended immutable feature descriptors with required and optional feature
  dependencies, compatibility and conflict declarations, parent-feature and
  category hierarchy metadata, and deterministic feature groups.
- Added an immutable Runtime Dependency Graph with required and optional edges,
  parent/child and reverse `required_by` relationships, deterministic
  dependency-first ordering, and required, optional, parent, and category cycle
  detection.
- Added the dependency graph to the built-in public Runtime Feature Registry
  catalogue with explicit registry, service, and capability requirements.
- Added metadata-only dependency validation, missing-dependency reporting,
  parent and category validation, and deterministic readiness propagation
  through required dependencies and feature parents.
- Added compatibility reports covering symmetric compatibility, missing and
  asymmetric declarations, active conflicts, and contradictory relationships.
- Embedded same-timestamp graph snapshots, relationship summaries, validation
  reports, and compatibility reports into Runtime Diagnostics and advertised
  graph availability through the Capability Manifest.
- Registered the graph through the existing DI container as a passive service,
  preserving lifecycle component order and the single diagnostics EventBus
  lifecycle path.
- Preserved BrainEngine, provider and AI execution, networking, Trusted
  Execution, Safe Execution, and all Version 1.4 and Sprint 1 compatibility
  behavior.
- Advanced application build metadata to `v1.5-s2` and increased the verified
  full-suite baseline from 1,058 to 1,068 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

### Version 1.5 — Sprint 1: Runtime Feature Registry

- Added immutable runtime feature descriptors covering identifier, display
  metadata, category, maturity, availability, service and capability
  requirements, safety level, commercial visibility, and experimental status.
- Added a thread-safe Runtime Feature Registry with duplicate rejection,
  deterministic identifier ordering, immutable category groups, immutable
  snapshots, and visibility-filtered public summaries.
- Added passive availability evaluation from same-timestamp Runtime Service
  Registry and Capability Manifest metadata without service resolution,
  discovery, probes, provider calls, networking, or feature execution.
- Integrated feature snapshots into Runtime Diagnostics and exposed feature
  registry availability through the Capability Manifest and existing
  diagnostics lifecycle events without adding a lifecycle component or event
  path.
- Added a built-in public catalogue for runtime diagnostics, service registry,
  capability manifest, and feature registry metadata surfaces.
- Advanced application build metadata to Version 1.5 Sprint 1 while preserving
  the Version 1.4 BrainEngine, Safe Execution, provider, lifecycle, and
  compatibility guarantees.
- Increased the verified full-suite baseline from 1,052 to 1,058 passing tests.
- No commit, release tag, or publication is part of this unreleased sprint.

## [1.4] - 2026-07-15

Version 1.4 completes three milestones while preserving the established Brain
execution path, public APIs, deterministic behavior, and trusted execution
boundaries:

1. **Milestone 1: Repository Professionalization**
2. **Milestone 2: AI Runtime Integration**
3. **Milestone 3: Runtime Observability**

Latest release tag: `v1.4-m3-sprint3`.

### Milestone 3: Runtime Observability

#### Sprint 3: Runtime Capability Manifest

- Added an immutable Runtime Capability Manifest covering runtime and build
  versions, supported subsystems, registered services, diagnostics, lifecycle,
  Conversation, AI Manager, EventBus, compatibility, and feature metadata.
- Added deterministic NOT_READY, PARTIAL, READY, and READINESS_UNKNOWN reports
  calculated exclusively from immutable diagnostics and registry metadata.
- Exposed architecture-only execution mode, disabled provider execution, and
  explicit inactive probing, networking, and AI execution feature flags.
- Integrated manifests into Runtime Diagnostics and DI through the existing
  diagnostics lifecycle EventBus path without new lifecycle components,
  duplicate events, service resolution, discovery, or startup-order changes.
- Preserved BrainEngine, Safe Execution, routing, orchestration, planner,
  automation, provider, network, UI, filesystem, and threading behavior.
- Increased the verified full-suite baseline from 1,045 to 1,052 passing tests.
- Tag: `v1.4-m3-sprint3`.

#### Sprint 2: Runtime Service Registry

- Added a typed Runtime Service Registry with immutable service records for DI
  type, order, lifecycle, dependency, source, compatibility, availability, and
  initialization metadata.
- Added deterministic dependency-graph, compatibility, and aggregate health
  reports calculated exclusively from retained runtime metadata.
- Integrated service registry snapshots with Runtime Diagnostics and the
  existing diagnostics lifecycle EventBus path without adding lifecycle steps
  or duplicate events.
- Preserved lazy factory behavior while ensuring registry snapshots never
  resolve services, invoke factories, probe providers, or execute callbacks.
- Preserved BrainEngine, routing, orchestration, planner, Safe Execution,
  provider, automation, network, UI, threading, and filesystem behavior.
- Increased the verified full-suite baseline from 1,037 to 1,045 passing tests.
- Tag: `v1.4-m3-sprint2`.

#### Sprint 1: Runtime Diagnostics

- Added immutable runtime diagnostics, build, lifecycle, compatibility, health,
  and deterministic summary models under `Core/diagnostics.py`.
- Added metadata-only health calculation for healthy, degraded, initializing,
  stopped, failed, and unknown runtime states without active probes.
- Exposed startup time, uptime, registered service names, AI Manager and
  Conversation state, EventBus and logger availability, runtime version, and
  build checkpoint metadata through the dependency-injected runtime.
- Registered diagnostics last in the existing component lifecycle and added
  single-path diagnostics started and stopped EventBus events.
- Preserved BrainEngine, AI provider, routing, orchestration, Safe Execution,
  automation, network, UI, and filesystem behavior.
- Increased the verified full-suite baseline from 1,026 to 1,037 passing tests.
- Tag: `v1.4-m3-sprint1`.

### Milestone 2: AI Runtime Integration

#### Sprint 3: Conversation-AI Runtime Bridge

- Added a typed, provider-neutral adapter between Phase 13 AI orchestration
  sessions and the Conversation runtime facade.
- Exposed immutable AI lifecycle, provider availability, and architecture-only
  execution metadata through Conversation sessions without provider instances.
- Composed Conversation and AI runtime lifecycle services through the existing
  dependency container, EventBus publishers, and deterministic system lifecycle.
- Preserved the BrainEngine execution path, Sprint 2 provider ordering,
  fail-closed availability, and disabled Phase 13 provider execution.
- Added focused runtime binding, event de-duplication, metadata, dependency
  injection, shutdown ordering, and compatibility coverage.
- Increased the verified full-suite baseline from 1,015 to 1,026 passing tests.
- Tag: `v1.4-m2-sprint3`.

#### Sprint 2: Provider Compatibility Adapters

- Added typed, immutable compatibility adapters for the existing OpenAI,
  Gemini, Claude, Ollama, and ordered fallback provider implementations.
- Registered safe provider snapshots through the existing AI manager, provider
  registry, EventBus, logger, and application lifecycle composition.
- Preserved the legacy Brain execution path and local provider fallback behavior
  while exposing deterministic Phase 13 provider routing and fallback chains.
- Added network-free compatibility, metadata, fail-closed registration, routing,
  rollback, lifecycle, and regression coverage.
- Increased the verified full-suite baseline from 996 to 1,015 passing tests.
- Tag: `v1.4-m2-sprint2`.

#### Sprint 1: AI Manager Runtime Composition

- Composed the Phase 13 AI Manager through the existing dependency container,
  lifecycle coordinator, EventBus, and logger.
- Preserved the BrainEngine text-processing path and kept AI Manager routing and
  architecture-only plans out of execution.
- Added deterministic runtime registration, lifecycle, event, and compatibility
  coverage.
- Increased the verified full-suite baseline from 994 to 996 passing tests.
- Tag: `v1.4-m2-sprint1`.

### Milestone 1: Repository Professionalization

- Synchronized project state, architecture, roadmap, recovery, onboarding, and
  version-history documentation with the Version 1.3 repository checkpoint.
- Recorded Phases 1 through 13 as complete, latest tag
  `v1.3-phase13-sprint3`, and the verified 994-test baseline.
- Defined Version 1.4 direction and non-goals without modifying
  runtime behavior, execution paths, public APIs, tests, or architecture.
- Tag: `v1.4-milestone1`.

## [1.3] - 2026-07-15

Version 1.3 completes Phase 13 while preserving the established Brain,
provider boundaries, compatibility aliases, and Trusted Execution Gateway.

### Phase 13 - AI Orchestrator

- Sprint 1 added immutable AI provider models and contracts, registry,
  provider lifecycle, and the additive AI manager facade. Tag:
  `v1.3-phase13-sprint1`.
- Sprint 2 added capability policy, deterministic scoring and ranking, typed
  routing results, and fallback planning. Tag: `v1.3-phase13-sprint2`.
- Sprint 3 added preference resolution, capability/provider negotiation,
  immutable sessions, selection records, architecture-only plans, summaries,
  lifecycle events, and thread-safe storage. Tag: `v1.3-phase13-sprint3`.
- Orchestration plans remain planned and unexecuted.

### Testing

- 994 automated tests passing.

## [1.2] - 2026-07-15

Version 1.2 completed Phases 9 through 12.

### Phase 11 - Safe Execution

- Added approval-bound sessions and queues, immutable previews, risk summaries,
  readiness decisions, validation, events, state transitions, and deterministic
  coordination.
- Tags: `v1.2-phase11-sprint1`, `v1.2-phase11-sprint2`, and
  `v1.2-phase11-sprint3`.

### Phase 12 - Human Interaction

- Added Conversation core sessions/history, context windows, search, summaries,
  topics, archive, export, cleanup, retention, and lifecycle coordination.
- Tags: `v1.2-phase12-sprint1`, `v1.2-phase12-sprint2`, and
  `v1.2-phase12-sprint3`.

### Added

- Live Wikipedia, weather, and Google News providers with grounded internet routing, source-aware news queries, and safe follow-up handling across research and news turns.
- Observe-only Self-Evolution phases 1 through 5, including capability inventory, discovery/evaluation records, approval-controlled proposals, deterministic change planning, typed execution-boundary request/authorization records, and durable verification-run/observation/outcome records that still stop before host mutation.
- Self-Evolution Phase 7 narrow mutation safety: typed mutation models, a deny-by-default surface registry, protected target restrictions, guard validation, exact human mutation approvals, and placeholder sequential mutation-run outcomes.
- Self-Evolution Phase 8 controlled executor foundations: sandbox, package, source, plugin, and Git executor services with typed validation, rollback metadata, and explicit simulation-only runtime selection.
- Self-Evolution Phase 9 planning intelligence: typed task planning, risk analysis, deterministic dependency scheduling, workflow composition, and execution-readiness decisions with execution disabled.
- Self-Evolution Phase 10 future-execution simulation: typed action registry, immutable execution contexts, fail-closed validation, and deterministic desktop, application, browser, and workflow simulations.

### Changed

- Recovery and continuity documentation now tracks the active modular runtime, roadmap checkpoints, and hygiene rules needed to resume development safely.
- The Evolution runtime registers the Phase 7 through 10 services through dependency injection while preserving the proposal, approval, verification, recovery, mutation, and rollback gates.
- Runtime execution remains `observe_only`, explicit-only, fail-closed, and simulation-only; it performs no automatic filesystem, package, Git, plugin, desktop, application, browser, network, or OS action.

## [1.2 Beta] - Historical Preparation Checkpoint

Version 1.2 Beta preparation extends the Version 1.1 Stable architecture through
Phase 10 while preserving existing APIs, command forms, runtime behavior, and
trusted execution boundaries.

### Phase 9 - Skill and Agent Frameworks

#### Sprint 1 - Skill Framework Foundation

- Added `Skills/core/` with typed skill metadata, definitions, capabilities,
  categories, factories, and lifecycle exceptions.
- Added `SkillRegistry`, `SkillLoader`, and `SkillManager` for deterministic
  registration, lookup, loading, unloading, logging, and event publication.
- Preserved the established `Skills/framework.py` API and existing built-in,
  memory, internet, and desktop skill paths.

#### Sprint 2 - Skill Discovery and Resolution

- Added `SkillDiscovery` for filtered catalog discovery.
- Added `CapabilityMatcher` for deterministic capability scoring and candidate
  ranking.
- Added `SkillResolver` for capability, category, availability, and preference
  aware resolution results.
- Extended `SkillManager` with discovery, matching, and resolution operations.

#### Sprint 3 - Agent Planning

- Added `Agents/core/` with typed planning contexts, plans, plan steps,
  workflows, planning results, and validation errors.
- Added `TaskPlanner`, `WorkflowValidator`, and `AgentRuntime` for
  dependency-aware, deterministic plan construction and validation.
- Kept the Agent Framework planning-only; it does not execute plan steps or
  bypass the Trusted Execution Gateway.

### Phase 10 - Computer and Desktop Integration

#### Sprint 1 - Computer Integration Foundation

- Added typed computer provider, capability, health, status, and information
  models under `Computer/core/`.
- Added `ComputerRegistry` and `ComputerManager` for provider registration,
  lifecycle management, health reporting, and capability discovery.
- Added explicit provider and lifecycle exception boundaries with optional
  logging and event publication.

#### Sprint 2 - Computer Information Services

- Added provider-backed `ApplicationService`, `FileSystemService`,
  `ProcessService`, and `ClipboardService`.
- Added typed application, filesystem, process, and clipboard metadata.
- Kept the new information services read-only by contract while retaining the
  legacy `Computer/` control APIs for backward compatibility.

#### Sprint 3 - Desktop Integration Layer

- Added `Computer/desktop/` with typed display, window, mouse, keyboard, and
  pointer-state models.
- Added `DisplayManager`, `WindowManager`, `MouseInterface`, and
  `KeyboardInterface` over injected inspection providers.
- Added `DesktopProvider` to combine desktop inspection contracts with the
  Computer provider lifecycle.
- Kept the layer interface-only so it introduces no unrestricted OS execution
  path.

### Major Architectural Milestones

- Completed project Phases 1 through 10.
- Separated typed capability discovery from plan construction and plan
  execution.
- Established provider registries and lifecycle managers for both skills and
  computer integrations.
- Added a validated planning-only agent boundary and typed desktop inspection
  boundary.
- Preserved the Version 1.1 Stable composition root, legacy Skills and Computer
  APIs, plugin architecture, EventBus integration, and fail-closed Trusted
  Execution Gateway.
- Synchronized the primary project documentation for Version 1.2 Beta
  preparation.

### Testing

- 687 automated tests passing.
- Increased the full-suite baseline from 559 tests at Version 1.1 Stable to 687
  tests for Version 1.2 Beta preparation, an increase of 128 tests.
- Added focused coverage for typed skills, discovery and resolution, agent
  planning, computer providers and information services, and desktop
  integration.

### Release Tags

- `v1.2-phase9-sprint1` - Phase 9 Skill Framework foundation.
- `v1.2-phase9-sprint2` - Phase 9 skill discovery and resolution.
- `v1.2-phase9-sprint3` - Phase 9 agent planning.
- `v1.2-phase10-sprint1` - Phase 10 Computer Integration foundation.
- `v1.2-phase10-sprint2` - Phase 10 computer information services.
- `v1.2-phase10-sprint3` - Phase 10 Desktop Integration Layer.

## [1.1 Stable] - 2026-07-14

Version 1.1 Stable completes the planned work through Phase 8, including all
three Trusted Execution Gateway sprints.

### Added

- AI Brain orchestration with intent classification, routing, prompt and response construction, provider adapters, skills integration, and conversation context.
- Memory services for short-term, long-term, session, profile, semantic, and persistent storage, plus context recovery, ranking, recall, forgetting, and memory-assisted reasoning.
- Dashboard services for runtime health, system metrics, logs, module testing, runtime insights, and lifecycle controls.
- Voice foundations for audio capture, speech recognition, text-to-speech, wake-word detection, session management, and runtime health reporting.
- Vision foundations for camera and screenshot capture, image loading and preprocessing, OCR, detection, and composable analysis.
- Internet services for safe provider-backed search, grounded research, news, weather, Wikipedia, HTTP access, caching, and diagnostics.
- Trusted Execution Gateway with typed, fail-closed request validation and execution lifecycle events.
- Hierarchical and action-specific Permission Engine.
- Rule-based Risk Analyzer and configurable trust policies.
- Approval Manager with explicit allow, deny, and approval-required decisions.
- Execution Dispatcher with injectable route-specific interfaces.
- Verification Engine for completion and expected-outcome validation.
- Rollback Manager for typed rollback plans, provider registration, and simulation-oriented recovery results.
- Append-only Audit Logger with immutable records, request correlation, optional persistence backends, and export support.

### Improved

- Plugin framework with descriptors, managed hooks, registry metadata, load-state tracking, and runtime-visible plugin counts.
- EventBus integration across application lifecycle, dashboard, plugins, memory, voice, vision, trusted execution, and other runtime services.
- Dependency-injected runtime composition, health checks, and subsystem registration.
- Desktop, automation, skills, and observe-only evolution foundations used by the modular runtime.

### Testing

- 559 automated tests passing across AI, memory, voice, vision, internet, dashboard, desktop, automation, evolution, plugins, and trusted execution.

## [1.1.0] - 2026-07-02

### Added

- Natural-language desktop command pipeline built on top of the existing Skills framework.
- Runtime registration for desktop command registry, executor, and pipeline services.
- Natural-language handlers for screenshots, clipboard actions, text entry, key presses, application launch and close, and window listing and focus.
- Universal Windows application resolver that searches Start Menu shortcuts, desktop shortcuts, PATH, Program Files, LocalAppData, registry uninstall entries, and Windows App Execution Aliases.

### Changed

- Reworked `desktop.control` to delegate all command parsing to a shared pipeline instead of duplicating desktop action logic inside the built-in skill.
- Reused Brain intent and route metadata when resolving desktop commands so question-style requests such as screenshot prompts can still execute through the runtime skill path.
- Extended unit coverage for natural-language desktop commands, Brain integration, and runtime dependency registration.
- Replaced hardcoded Windows application aliases with dependency-injected resolver-backed application launching in `ApplicationManager`.

### Compatibility

- Preserved NARVIS v1.0 desktop command forms such as `copy ...`, `open application ...`, and `focus window ...`.
- Kept the existing Brain, Router, Skills, and DesktopControlService architecture intact.

## [2.0.0] - 2026-06-29

### Added

- Initial project scaffold and package structure.
- Core architecture foundation modules.
- Project development guide.
- Repository configuration files for professional development.

### Notes

- This release contains the initial repository setup and architecture foundation only.
- No application functionality has been implemented yet.
