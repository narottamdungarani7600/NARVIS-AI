# Changelog

All notable changes to NARVIS will be documented in this file.

## [Unreleased]

### Added
- Live Wikipedia, weather, and Google News providers with grounded internet routing, source-aware news queries, and safe follow-up handling across research and news turns.
- Observe-only Self-Evolution phases 1 through 4, including capability inventory, discovery/evaluation records, approval-controlled proposals, deterministic change planning, and typed execution-boundary request/authorization records that stop before host mutation.

### Changed
- Recovery and continuity documentation now tracks the active modular runtime, roadmap checkpoints, and hygiene rules needed to resume development safely.

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
