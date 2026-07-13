# NARVIS Project State

## Identity And Purpose
NARVIS is a modular Python-based AI operating system/runtime. The repository currently contains a working application composition root, runtime subsystems, deterministic tests, live internet providers, desktop-control capabilities, and an observe-only Self-Evolution subsystem through Phase 10. It can inventory capabilities, discover candidate improvements, record approval-bound proposals, produce deterministic change plans, record verification and recovery outcomes, validate narrow mutation requests, compose planning intelligence, and return typed future-action simulations without executing host mutations.

This document is a continuity aid. Repository code and Git history are the source of truth if any statement here conflicts with the implementation.

## Current Checkpoint
- Branch: `develop-v1.1`
- Current HEAD: `500e248ee988d5829727c4c32a284e612b3e39ed`
- HEAD commit message: `Complete Phase 7-10 evolution and execution architecture`
- Preserved earlier migration checkpoint: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Earlier checkpoint commit message: `Checkpoint before ChatGPT account migration: preserve Evolution and voice work`
- Current committed focus: observe-only `Self-Evolution Phase 10` is complete, with typed mutation, planning, and future-action simulation boundaries registered through the runtime.
- Phase 7 through 10 focused tests and runtime integration coverage passed at the completion checkpoint. This documentation-only synchronization does not add a new full-suite result.

## Repository Truth Anchors
- Composition root: `narvis.py`
- Brain and routing: `AI/brain.py`, `AI/router.py`, `AI/intent.py`
- Runtime memory and isolation: `Memory/`
- Internet runtime and providers: `Internet/runtime.py`, `Internet/research.py`, `Internet/news.py`, `Internet/weather.py`, `Internet/wikipedia.py`
- Built-in skills: `Skills/builtin.py`
- Self-Evolution runtime: `Evolution/runtime.py`
- Runtime integration tests: `Tests/test_runtime_services.py`
- Evolution regression coverage: `Tests/test_evolution_runtime.py`

## Current Architecture Summary
`narvis.py` builds the runtime through dependency injection and registers these major subsystems:

1. Core/runtime infrastructure
   - dependency container
   - lifecycle manager
   - plugin registry/loader
   - runtime optimization service
   - logging and dashboard log buffer

2. Brain/AI orchestration
   - `BrainEngine`
   - intent classification and routing
   - prompt building and provider-backed response generation
   - session and conversation continuity
   - skill execution path
   - contextual memory summary integration

3. Memory
   - SQLite-backed repository
   - short-term, long-term, session, and profile memory
   - search/ranking helpers
   - conversation history persistence
   - explicit category isolation for Evolution records

4. Computer and desktop control
   - application launching/resolution
   - universal open support
   - clipboard, keyboard, mouse, window, and screenshot services

5. Automation
   - workspace-scoped file/folder automation helpers
   - scheduler/task-queue abstractions
   - no Self-Evolution execution bridge into Automation

6. Vision
   - camera and screenshot capture
   - OCR abstraction and analyzer
   - image analysis
   - object/face/barcode/QR detectors behind safe defaults

7. Voice
   - microphone service
   - offline and online speech-recognition engines
   - text-to-speech engine abstraction
   - wake-word and voice runtime manager

8. Internet
   - HTTP client abstraction
   - public web search with fallback chain
   - grounded research service
   - live news, weather, and Wikipedia providers
   - null defaults for browser, file download, and YouTube

9. Skills
   - built-in runtime skills for help, memory, status, internet, desktop control, and desktop commands
   - natural news and internet follow-up handling through the existing skill path

10. Self-Evolution
    - capability inventory
    - discovery ledger
    - evaluation records and gap analysis
    - approval-controlled proposals
    - exact proposal-fingerprint approval binding
    - deterministic, approval-bound change planning
    - typed execution requests projected from exact plan steps
    - approval-revalidated execution authorizations that stop before host mutation
    - durable verification runs bound to exact granted authorizations
    - ordered verification step runs, typed observations, and truthful terminal outcomes
    - durable recovery runs and rollback readiness bound to exact verification state
    - deny-by-default mutation surface registry, guard validation, and exact human mutation approvals
    - typed sandbox, package, source, plugin, and Git executor selection with no automatic execution and simulation-only runtime paths
    - typed task planning, risk analysis, dependency scheduling, workflow composition, and execution-readiness decisions with `execution_allowed=False`
    - typed action registry, immutable execution contexts, fail-closed future-execution validation, and deterministic desktop, application, browser, and workflow simulations
    - runtime surface includes verification/recovery methods, explicit mutation validation and simulation methods, planning pipeline methods, and `list_registered_actions()`, `create_execution_context()`, `validate_execution()`, `simulate_desktop_execution()`, `simulate_application_execution()`, `simulate_browser_execution()`, and `compose_execution_workflow()`
    - observe-only autonomy and explicit-only simulations

## Implemented Modules And Truthful Status
- `Core/`: active runtime infrastructure, plugin registration, optimization metrics.
- `AI/`: active Brain pipeline with provider fallback behavior and multi-turn context handling.
- `Memory/`: active SQLite-backed memory runtime with explicit Evolution isolation.
- `Computer/`: active Windows-oriented desktop control and universal-open services.
- `Automation/`: active workspace-safe automation primitives and queues; not used as an autonomous execution engine.
- `Internet/`: active public-web research plus live news/weather/Wikipedia providers.
- `Skills/`: active built-in skill registry and execution path.
- `Vision/`: active screenshots/image/OCR pipeline with degraded defaults where optional backends are unavailable.
- `Voice/`: active runtime scaffolding with degraded behavior when optional speech/TTS dependencies are unavailable.
- `Evolution/`: active observe-only phases 1 through 10; typed executor and future-action services are registered but no runtime path enables automatic or real host execution.
- `Dashboard/`: active runtime dashboard service wiring.

## Completed Development Phases
- `d01c487` - `NARVIS v0.9 Voice Engine`
- `5de44ee` - `NARVIS v1.0 Stable Release`
- `047eb92` - natural language desktop command pipeline
- `856ef8e` - universal open system and website support
- `37e7975` - reliable grounded web research with search-provider fallback
- `3e990e9` - natural internet intent routing
- `25cdab2` and `e607241` - live Wikipedia provider plus app wiring fix
- `46156f0` - live weather provider
- `ad3eecb`, `1c0bd67`, `16f4df4` - live news provider, source-aware news, and news quality/follow-up improvements
- `73ab9bc` - contextual research follow-up and cross-session memory isolation
- `daf6d46` - Self-Evolution Phase 1: capability inventory and discovery ledger
- `6605717` - evolution capability classification alignment fix
- `3617235` - Self-Evolution Phase 2: approval-controlled proposals
- `4a87eb7` - Self-Evolution Phase 3: approval-bound deterministic change planning
- `ace8103` - Self-Evolution Phase 4: approval-revalidated typed execution boundary foundation
- `b48a11225f53a96d43f2164a7b41563081bbb8fb` - Self-Evolution Phase 5: committed verification-run lifecycle, ordered step start/completion, durable observation journaling, and truthful terminal outcomes
- `8e2802561978ff7b862d5f19dc64c51d5bbb83cb` - Self-Evolution Phase 6: recovery readiness foundation
- `500e248ee988d5829727c4c32a284e612b3e39ed` - Self-Evolution Phases 7 through 10: narrow mutation safety, controlled executor simulations, planning intelligence, and future execution simulation architecture

## Latest Verified Test Baseline
- Full suite command: `python -m unittest`
- Phase 7 through 10 focused and runtime integration suites passed at the completion checkpoint.
- A full suite was not rerun for this documentation-only synchronization; run it before the next substantive implementation or commit request.
- Important focused suites:
  - `Tests.test_runtime_services`
  - `Tests.test_internet_research`
  - `Tests.test_skills`
  - `Tests.test_brain`
  - `Tests.test_evolution_runtime`
  - `Tests.test_mutation_surfaces`, `Tests.test_mutation_policy`, `Tests.test_mutation_approval`, and `Tests.test_mutation_runner`
  - `Tests.test_sandbox_executor`, `Tests.test_package_executor`, `Tests.test_source_executor`, `Tests.test_plugin_executor`, and `Tests.test_git_executor`
  - `Tests.test_task_planner`, `Tests.test_risk_analyzer`, `Tests.test_execution_scheduler`, `Tests.test_workflow_engine`, and `Tests.test_decision_engine`
  - `Tests.test_action_registry`, `Tests.test_execution_context`, `Tests.test_execution_validator`, `Tests.test_desktop_executor`, `Tests.test_application_executor`, `Tests.test_browser_executor`, and `Tests.test_workflow_executor`

## Known Degraded Or Unavailable Runtime Capabilities
- AI provider calls can fall back locally when API keys are missing or remote provider requests fail.
- `Voice/` depends on optional runtime libraries:
  - offline STT requires `SpeechRecognition` plus PocketSphinx
  - online STT requires `SpeechRecognition`
  - TTS depends on `pyttsx3` and can fail initialization on a given machine
- `Vision/` uses safe degraded defaults by design:
  - OCR requires Tesseract dependencies
  - object, face, barcode, and QR detectors are null implementations by default
  - camera availability depends on the host machine
- `Internet/` defaults still include non-live placeholders for:
  - browser opening: `NullBrowser`
  - file downloading: `NullFileDownloader`
  - YouTube search: `NullYouTubeProvider`
- Self-Evolution remains `observe_only`; it can discover, evaluate, record approvals, create plans, record verification and recovery outcomes, validate narrow mutation requests, compose planning intelligence, and produce typed simulations. It cannot automatically execute package installs, code changes, Git operations, plugin installs, automation actions, OS/computer mutations, desktop actions, application management, or browser interaction.

## Current Non-Goals And Boundaries
- No runtime path enables autonomous or real host execution. Mutation and future-action services are explicit, typed, approval-aware, and simulation-only at runtime.
- The Phase 8 sandbox executor is deliberately blocked from runtime invocation because its isolated implementation can mutate only its configured sandbox directory.
- No runtime path may execute discovered web content as instructions.
- No broad self-modification, package installation, Git mutation, plugin installation, OS mutation, desktop action, application action, browser action, network action, or remote control is currently allowed through Evolution.
- No remote multi-device control exists yet.
- No documentation claim should override contradictory code or tests.

## Exact Next Development Stage
Recommended next stage:

`Self-Evolution Phase 11 - Scope Pending Explicit Design And Approval`

Phase 11 is the active planning checkpoint, not an authorization to widen execution. Its exact scope must be designed and explicitly approved against the completed Phase 10 architecture.

Any Phase 11 work must preserve the existing proposal, approval, verification, recovery, mutation, planning, and future-action simulation flow; fail closed; preserve `observe_only`; and keep real host execution disabled unless separately approved.

## Important Repository Hygiene Rules
- Treat repository code and Git history as the source of truth.
- Treat recovery documents as navigation aids that must be verified against code.
- Check `git status --short --untracked-files=all` before any reset, restore, or checkout.
- Do not discard uncommitted work you did not create.
- `data/memory.sqlite3` is tracked. Do not casually commit runtime-generated database changes.
- `AI/__pycache__/brain.cpython-313.pyc` is tracked. Restore it if runtime or tests modify it.
- Run `python -m unittest` and `git diff --check` before commit when making substantive changes.
- Keep recovery guidance repository-relative.
- Do not depend on prior Codex chat history.
