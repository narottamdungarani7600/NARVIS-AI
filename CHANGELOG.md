# Changelog

All notable changes to NARVIS will be documented in this file.

## [1.1.0] - 2026-07-02

### Added
- Natural-language desktop command pipeline built on top of the existing Skills framework.
- Runtime registration for desktop command registry, executor, and pipeline services.
- Natural-language handlers for screenshots, clipboard actions, text entry, key presses, application launch and close, and window listing and focus.

### Changed
- Reworked `desktop.control` to delegate all command parsing to a shared pipeline instead of duplicating desktop action logic inside the built-in skill.
- Reused Brain intent and route metadata when resolving desktop commands so question-style requests such as screenshot prompts can still execute through the runtime skill path.
- Extended unit coverage for natural-language desktop commands, Brain integration, and runtime dependency registration.

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
