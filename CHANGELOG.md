# Changelog

All notable changes to NARVIS will be documented in this file.

## [Unreleased]

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

## [1.2 Beta] - In Development

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
