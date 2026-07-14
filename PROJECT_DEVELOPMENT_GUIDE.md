# NARVIS Project Development Guide

## 1. Project Vision

NARVIS (Next-Generation AI Virtual Intelligent Response System) is a modular, scalable, and professional Python-based AI operating system. The current runtime integrates AI reasoning, conversation, memory, voice and vision foundations, automation, internet services, dashboard monitoring, plugins, and events. The project also includes composable trusted execution components under `Core/execution/`.

The development goal is to extend this platform while preserving clarity, maintainability, reliability, explicit trust boundaries, and long-term growth.

---

## 2. Architecture Principles

The architecture of NARVIS must follow these principles:

- Favor modularity over monoliths.
- Keep business logic independent from infrastructure concerns.
- Promote loose coupling between subsystems.
- Encourage high cohesion within each package and module.
- Design for extension, not modification.
- Make the system easy to test and reason about.
- Keep interfaces stable and reusable.
- Prepare every module for future integration with other domains.

All new features must fit the existing architectural boundaries and should not bypass the established package structure.

### Natural Language Command Flows

Natural-language command features must extend the existing runtime flow instead of creating parallel orchestration paths.

- Reuse the shared Brain intent classification and routing services whenever command handling depends on user intent.
- Keep command interpretation in reusable pipeline or service modules rather than duplicating string parsing inside UI-facing adapters or skills.
- Route desktop-oriented commands through `DesktopControlService` or another existing facade instead of calling lower-level device managers directly from high-level orchestration code.
- Register new command pipelines through dependency injection so they can be replaced, tested, and extended at runtime.
- Preserve backward compatibility for established command phrases unless a breaking change is explicitly planned and documented.

### Trusted Execution Changes

Execution-related features must preserve the Phase 8 trust boundary in `Core/execution/`.

- Use typed execution requests and results.
- Keep permission, risk, policy, approval, dispatch, verification, rollback, and audit services replaceable through dependency injection.
- Fail closed when request validation or any authorization dependency fails.
- Never bypass authorization by calling a dispatcher directly from the Brain, dashboard, skill, or plugin layer.
- Register host-capable dispatch interfaces explicitly and preserve request correlation across lifecycle records.
- Treat rollback as an explicit, typed recovery boundary; do not imply that a simulated rollback has mutated the host.
- Publish execution events without exposing request parameters or secrets.

---

## 3. SOLID Principles

All modules must respect the SOLID principles:

- Single Responsibility Principle: each class or module should have one clear responsibility.
- Open/Closed Principle: modules should be open for extension but closed for unnecessary modification.
- Liskov Substitution Principle: implementations of interfaces and abstractions must be substitutable.
- Interface Segregation Principle: avoid forcing modules to depend on irrelevant methods.
- Dependency Inversion Principle: depend on abstractions, not concrete implementations.

Any new module must be designed so that higher-level components depend on stable contracts instead of brittle implementations.

---

## 4. Clean Architecture Guidelines

NARVIS should follow Clean Architecture principles:

- Keep core domain logic independent from external frameworks, APIs, and runtime assumptions.
- Separate domain abstractions from infrastructure implementations.
- Allow use cases and services to depend on interfaces defined in the Core layer.
- Avoid placing framework-specific logic in business-facing modules.
- Ensure that the system can evolve without rewriting the foundation.

The Core package is the architectural center of the project. Other packages must rely on its abstractions rather than create hidden coupling.

---

## 5. Python Coding Standards

Python code in NARVIS must follow professional standards:

- Use Python 3.10+ compatible syntax.
- Write clear, readable, and explicit code.
- Prefer readability over cleverness.
- Use docstrings for all public modules, classes, functions, and methods.
- Keep functions focused and concise.
- Avoid unnecessary global state.
- Favor composition over inheritance where appropriate.
- Keep dependencies minimal and explicit.
- Use standard library tools first before introducing third-party libraries.

Code should be written as if it will be reviewed by other engineers in a long-running software project.

---

## 6. Naming Conventions

Consistent naming is mandatory.

- Use snake_case for modules, functions, variables, and methods.
- Use PascalCase for classes.
- Use UPPER_CASE for constants.
- Use descriptive names that communicate purpose clearly.
- Avoid abbreviations unless they are widely accepted and documented.
- Prefer domain-focused names over implementation-specific names.

Examples:
- module: startup.py
- class: StartupManager
- function: initialize_system
- constant: DEFAULT_TIMEOUT

---

## 7. Folder Responsibilities

Each top-level package has a defined responsibility:

- Core: foundational abstractions, interfaces, configuration, engines, lifecycle coordination.
- Core/execution: permission, risk, policy, approval, dispatch, verification, rollback, audit, and trusted execution models.
- AI: orchestration and AI reasoning components.
- Voice: speech recognition, speech synthesis, and voice interaction services.
- Vision: image and video processing capabilities.
- Memory: persistent and ephemeral memory systems.
- Skills: reusable intelligent capabilities and task modules.
- Internet: external network, API, and web interaction services.
- Automation: task execution and operational automation.
- Computer: desktop, application, window, input, clipboard, screenshot, and universal-open services.
- Dashboard: runtime UI, health, metrics, logs, insights, tests, and lifecycle controls.
- Evolution: observe-only capability discovery, planning, approval, verification, recovery, validation, and simulation services.
- Config: environment and application configuration structures.
- Assets: static resources such as models, images, and documents.
- Logs: logging output and runtime diagnostics.
- Tests: automated testing and validation.
- Docs: design documents, developer guides, and technical references.

New modules must be placed in the package that best matches their responsibility.

---

## 8. Logging Standards

Logging must be consistent and professional.

- Use structured logging where possible.
- Log important lifecycle events, errors, and state transitions.
- Avoid noisy logs in normal operation.
- Do not log secrets, tokens, or sensitive user data.
- Use severity levels consistently.
- Logging should be injectable and testable.

A logger abstraction should be used rather than direct print statements in core modules.

---

## 9. Error Handling Policy

Error handling must be explicit and predictable.

- Catch and handle exceptions at the appropriate level.
- Do not swallow errors silently.
- Raise meaningful exceptions with descriptive messages.
- Prefer domain-specific exceptions over generic ones when useful.
- Fail fast when configuration or dependencies are invalid.
- Ensure that errors are logged and surfaced clearly.

Modules should never rely on undefined behavior or hidden failure paths.

---

## 10. Documentation Standards

All significant modules must be documented.

- Every public module, class, function, and method must include a docstring.
- README files must describe purpose, usage, and structure.
- Complex workflows should include dedicated documentation in the Docs folder.
- Keep documentation aligned with the actual implementation.
- Use concise but complete language.

Documentation is part of the implementation contract and must be maintained alongside code.

---

## 11. Type Hint Requirements

Type hints are mandatory for all new Python code.

- Use built-in types where possible.
- Use typing constructs such as Protocol, Optional, Union, and Literal when appropriate.
- Avoid untyped function signatures.
- Prefer explicit return types.
- Use dataclasses or typed containers for structured data.

Type hints must improve clarity and reduce ambiguity, not just satisfy style requirements.

---

## 12. Testing Strategy

Testing is required for all stable and reusable components.

- Write unit tests for isolated logic.
- Write integration tests where multiple modules interact.
- Use automated tests for configuration, logging, lifecycle flows, and component coordination.
- Keep tests deterministic and independent.
- Test both success and failure paths.
- Cover natural-language command features with unit tests for parsing, runtime registration, and subsystem integration.
- Prefer small, focused tests over large end-to-end tests for early development.

The project should be built with testability in mind from the beginning.

---

## 13. Security Guidelines

Security must be considered in every module.

- Never hardcode secrets or credentials.
- Validate and sanitize external input.
- Limit privileges and avoid unnecessary access.
- Use secure configuration handling practices.
- Protect sensitive data at rest and in transit.
- Avoid exposing internal implementation details in user-facing flows.

Security is a design requirement, not a later concern.

---

## 14. Plugin Architecture Guidelines

NARVIS supports plugin-style expansion through plugin descriptors, the plugin registry, managed hooks, and the Core plugin loader.

- Define stable interfaces for extensible functionality.
- Keep plugin hooks explicit and well documented.
- Avoid hard-wiring plugin dependencies into core modules.
- Support optional registration and composition.
- Register plugin services through the shared dependency container and publish only structured, non-sensitive events.
- Preserve plugin load-state reporting and isolate plugin failures at the hook boundary.
- Maintain backward compatibility for interface changes whenever possible.

Voice, Vision, Memory, Automation, Skill, Internet, and future integration modules should remain pluggable components that integrate through shared contracts.

---

## 15. Scalability Rules

The system must be designed for future growth.

- Prefer horizontal and vertical separation of responsibilities.
- Keep modules decoupled so they can scale independently.
- Avoid unnecessary shared mutable state.
- Design services so they can be extended without architectural rewrites.
- Prepare the foundation for multi-threaded, multi-process, or distributed execution in later phases.

Scalability should be achieved through architecture and composition, not ad hoc patching.

---

## 16. Performance Guidelines

Performance should be considered throughout development.

- Avoid unnecessary allocations and repeated work.
- Use efficient data structures where needed.
- Keep hot paths simple and predictable.
- Profile before optimizing.
- Prefer clear design over premature micro-optimization.
- Ensure modules remain responsive under increasing workloads.

Performance improvements must be justified by measurable need and maintainable implementation.

---

## 17. Module Development Contract

Every future module must:

- Follow the package responsibility model.
- Include complete docstrings.
- Include type hints.
- Remain independent and reusable.
- Integrate through abstractions where appropriate.
- Be covered by tests when behavior is significant.
- Be documented clearly.

This guide is the engineering contract for the NARVIS project and must be followed for all future development work.
