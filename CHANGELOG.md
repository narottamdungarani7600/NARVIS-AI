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
