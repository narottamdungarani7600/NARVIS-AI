# NARVIS Project Development Guide

## 1. Project Vision

NARVIS (Next-Generation AI Virtual Intelligent Response System) is a modular,
scalable, and professional Python-based AI operating system. Version 1.3 is
complete on the `develop-v1.1` branch at tag `v1.3-phase13-sprint3`. The current architecture integrates
AI reasoning, conversation, memory, voice and vision foundations, internet
services, typed skills, planning-only agents, computer and desktop integration,
automation, dashboard monitoring, plugins, events, and composable trusted
execution components under `Core/execution/`.

Phases 11 through 13 add approval-bound Safe Execution coordination,
Conversation core/context/lifecycle, and provider-agnostic AI Core, Routing,
and Orchestrator layers. The verified checkpoint contains 994 passing tests.

The development goal is to extend this platform while preserving clarity,
maintainability, reliability, complete backward compatibility, explicit trust
boundaries, and long-term growth.

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
- Keep capability discovery and agent planning separate from execution.
- Introduce provider-based Computer and Desktop integrations without removing or
  silently changing legacy Computer APIs.
- Preserve public APIs, command forms, and execution behavior unless a breaking
  release is explicitly designed, approved, and documented.

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
- Do not treat an Agent `Plan` or `PlanningResult` as execution authorization.
- Do not treat the Phase 10 Desktop inspection interfaces as an execution
  provider.
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
- AI/core: provider contracts, immutable models, registry, lifecycle, and AI
  manager services.
- AI/routing: capability policy, deterministic scoring, routing, and fallback.
- AI/orchestrator: preferences, negotiation, immutable sessions, plans,
  summaries, and lifecycle events; plans remain non-executing.
- Conversation: conversation core, context intelligence, and archive/export/
  cleanup lifecycle services.
- Execution: approval-bound sessions, previews, risk/readiness, validation,
  state transitions, and coordination under the Trusted Execution Gateway.
- Voice: speech recognition, speech synthesis, and voice interaction services.
- Vision: image and video processing capabilities.
- Memory: persistent and ephemeral memory systems.
- Skills: legacy runtime skills plus typed registration, loading, discovery,
  capability matching, and resolution under `Skills/core/`.
- Agents: planning contexts, typed plans and workflows, skill-backed task
  planning, validation, and planning-only runtime coordination.
- Internet: external network, API, and web interaction services.
- Automation: task execution and operational automation.
- Computer/core: provider contracts, registry, lifecycle management, health,
  capabilities, typed models, and integration errors.
- Computer/services: provider-backed, read-only application, filesystem,
  process, and clipboard information services.
- Computer/desktop: interface-only display, window, mouse, and keyboard
  inspection contracts.
- Legacy Computer modules: backward-compatible desktop, application, window,
  input, clipboard, screenshot, and universal-open services.
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
- Cover skill registration, loading, discovery, matching, and resolution.
- Cover agent plan construction, dependency validation, failure results, and
  the non-executing planning boundary.
- Cover Computer provider lifecycle, read-only information services, Desktop
  inspection contracts, invalid provider results, and event or logging failure
  isolation.
- Prefer small, focused tests over large end-to-end tests for early development.

The Version 1.3 completion baseline is 994 passing automated tests. New
work must preserve or increase that passing baseline. The project should be
built with testability in mind from the beginning.

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

## 17. Local Development Environment

### Repository setup

```powershell
git checkout develop-v1.1
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Python 3.10 or newer is required. Desktop integrations are currently
Windows-oriented. Audio, camera, OCR, and remote-provider behavior may require
optional dependencies, hardware, credentials, or network availability.

### Start-of-work checks

Run these checks before modifying the repository:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git log --oneline -12
```

Read `Docs/README.md`, the current state and roadmap, this guide, the software
architecture, and relevant source/tests. If the tree is already dirty, identify
and preserve existing work before editing.

### Focused development loop

1. Run the smallest relevant test module.
2. Make one cohesive, architecture-aligned change.
3. Re-run focused success, failure, and compatibility cases.
4. Review the diff for unintended files and runtime artifacts.
5. Update documentation when repository truth or public behavior changes.

### Completion checks

```powershell
python -m unittest discover -s Tests -p "test_*.py"
git diff --check
git status --short --untracked-files=all
```

The Version 1.3 reference baseline is 994 passing tests. The repository has no
checked-in Ruff, Black, Flake8, Pylint, or mypy configuration at this
checkpoint; run only configured or explicitly approved static gates and report
them accurately.

---

## 18. Development Workflow

NARVIS development follows this required sequence.

### 1. Architecture First

- Review `SOFTWARE_ARCHITECTURE.md`, this guide, relevant `Docs/` records, and
  the current implementation before proposing changes.
- Define package ownership, interfaces, data models, dependencies, trust
  boundaries, event behavior, compatibility constraints, and test strategy.
- Prefer extending an existing abstraction to creating a parallel orchestration
  or execution path.
- Record an architecture decision before implementation when a change crosses
  subsystem boundaries or materially changes a stable contract.

### 2. Codex Implementation

- Give Codex a bounded objective, explicit non-goals, compatibility
  requirements, expected files, and validation criteria.
- Implement the smallest cohesive change that satisfies the approved
  architecture.
- Keep source, tests, and documentation changes within the requested scope.
- Preserve existing APIs and behavior unless an approved change explicitly says
  otherwise.
- Never instruct an implementation tool to bypass the Trusted Execution Gateway
  or broaden host access implicitly.

### 3. Architecture Review

- Review the complete diff against the approved architecture before accepting
  implementation work.
- Verify package responsibility, dependency direction, provider and plugin
  boundaries, dependency injection, event payloads, logging, error handling,
  security, and backward compatibility.
- Confirm that skill discovery, agent planning, computer inspection, desktop
  inspection, and trusted execution remain distinct responsibilities.
- Reject unrelated edits, duplicated pathways, hidden global dependencies, or
  weakened trust boundaries.

### 4. Testing

- Run focused tests for every changed subsystem.
- Run the complete suite from the repository root:

```powershell
python -m unittest discover -s Tests -p "test_*.py"
```

- Compare the result with the current 994-test passing baseline.
- Run documentation, formatting, type, or static checks that apply to the
  change.
- Do not continue to version-control steps while required validation is failing.

### 5. Git Review and Commit

- Review `git status` and `git diff` and include only intended files.
- Run `git diff --check` and inspect staged changes separately from unstaged
  changes.
- Confirm generated data, logs, screenshots, databases, bytecode, and temporary
  directories are not included accidentally.
- Use a focused commit message that names the phase or documentation milestone.
- Commit only after architecture review and required validation pass.
- Do not combine unrelated refactors or generated artifacts with the change.
- Commit only after explicit commit approval.

### 6. Push

- Push the reviewed commit to its intended branch after confirming branch and
  remote state.
- For current Version 1.4 work, use `develop-v1.1` unless an explicitly approved
  branch plan says otherwise.
- Never force-push shared development or release history without explicit
  authorization and coordination.
- Push only after explicit push approval.

### 7. Release Tag

- Create a release or sprint tag only after the commit is pushed, the complete
  suite passes, documentation is synchronized, and the milestone is approved.
- Use the established annotated naming convention, such as
  `v1.3-phase13-sprint3`.
- Verify that the tag references the intended commit before pushing it.
- Do not move or reuse published tags.
- Push tags only after explicit release/tag approval.

Commit, push, and tag operations are separate approval and verification
checkpoints. A documentation or implementation request does not imply
authorization to perform them.

---

## 19. Release Workflow

A sprint or release is complete only when repository state and published
history agree.

1. Confirm approved scope and final diff.
2. Run focused validation and the complete regression suite.
3. Run `git diff --check` and applicable documentation/static checks.
4. Synchronize README, changelog, architecture, project state, roadmap, and
   recovery records where their claims changed.
5. Obtain separate commit approval, create the focused commit, and verify it.
6. Obtain separate push approval and push the intended branch.
7. Obtain separate tag approval, create an annotated sprint/release tag, verify
   its target, and push it.
8. Confirm the working tree, branch, remote, commit, and tag are truthful.

Never create a release merely because tests pass. Version naming, milestone
scope, documentation, compatibility, security, and operational readiness must
also be reviewed.

---

## 20. Recovery Workflow

Recovery is read-only until repository state is understood.

1. Stop implementation and inspect branch, HEAD, tag, status, diff, and recent
   history.
2. Follow `Docs/AI_DEVELOPMENT_RULES.md`, `Docs/CODEX_RECOVERY_PROMPT.md`, and
   `Docs/RECOVERY_CHECKLIST.md`.
3. Compare project-state and roadmap claims with source and tests.
4. Inspect relevant composition, provider, execution, conversation, and AI
   orchestration boundaries.
5. Separate intentional work from runtime artifacts without deleting either.
6. Run focused/full tests only when doing so will not overwrite uncommitted
   work; use bytecode-safe invocation where tracked artifacts are a concern.
7. Report discrepancies and obtain explicit approval before resuming mutation.

Do not reset, restore, checkout, clean, delete, or overwrite files during
recovery without explicit authorization.

---

## 21. Repository Policies

### Backward compatibility policy

- Treat exported names, constructor signatures, method behavior, immutable
  model semantics, event names, command forms, configuration keys, and
  compatibility aliases as public surfaces when existing callers or tests use
  them.
- Prefer additive fields with compatible defaults, additive methods, adapters,
  and deprecation shims.
- Do not remove or reinterpret a public surface in a minor or patch milestone.
- A deprecation must name its replacement, migration steps, warning period,
  proposed removal version, and tests for both old and new paths.
- A breaking change requires explicit major-version approval and a documented
  migration/recovery plan before implementation.

### Versioning policy

- Product versions describe completed, verified scope; roadmap text does not.
- Phase/sprint tags use the established form `v<version>-phase<phase>-sprint<sprint>`.
- Stable or beta labels may be used only when explicitly approved and
  documented.
- Published tags are immutable. Never move, reuse, or silently replace them.
- Changelog, state, roadmap, recovery, version tables, test counts, and tag
  references must agree at a release checkpoint.

### Branch strategy

The observed repository branches are `main`, `develop`, and `develop-v1.1`;
Version 1.4 work currently remains on `develop-v1.1`. Do not infer permission to
create, switch, merge, rebase, or promote branches. Each operation requires the
approved workflow for the current milestone.

When a short-lived branch is explicitly requested, use a focused name, keep its
scope narrow, and integrate only after review. Never force-push shared branches
or rewrite published release history.

### Documentation maintenance policy

Documentation is part of the deliverable, not post-release cleanup.

- Update the README when public capability, setup, limits, or roadmap changes.
- Update architecture and decisions when ownership, dependencies, contracts, or
  trust boundaries change.
- Update the development/contribution guides when engineering workflow changes.
- Update changelog, project state, roadmap, memory, and recovery documents at
  each completed checkpoint.
- Keep implemented capability, current work, proposed work, and non-goals
  visibly separate.
- Validate relative links, code fences, heading structure, test counts, branch,
  commit, and tag claims.

---

## 22. Repository Quality Gates

| Gate | Required evidence |
|---|---|
| Scope | Diff contains only approved files and behavior |
| Architecture | Ownership, dependency direction, invariants, and trust boundaries reviewed |
| Compatibility | Existing APIs, aliases, configuration, events, commands, and semantics preserved |
| Tests | Focused suites pass and full suite meets or exceeds the accepted baseline |
| Syntax/build | Changed source compiles using the repository-supported Python version |
| Documentation | Public, architecture, state, roadmap, changelog, and recovery claims synchronized as applicable |
| Hygiene | `git diff --check` passes; no accidental databases, logs, bytecode, screenshots, secrets, or temporary files |
| Security | Input validation, least privilege, sensitive logging, provider failure, and execution authority reviewed |
| Git | Branch, staged diff, commit, remote, and tag are truthful for the authorized stage |

If a tool is not configured in the repository, do not present it as a mandatory
or passing gate. Adding a formatter, linter, type checker, coverage threshold,
or build system is a separate engineering change requiring approval.

### Testing policy

- Every behavior change needs deterministic success, failure, validation, and
  compatibility coverage proportional to risk.
- Prefer unit tests at contract boundaries and integration tests for composition
  or cross-package behavior.
- Live network, credentials, wall-clock timing, hardware, and nondeterministic
  provider responses must not be required by the standard suite.
- Do not delete, skip, loosen, or rewrite unrelated tests to accept a change.
- Run focused tests while iterating and the complete suite before sprint
  completion, commit review, and release readiness.
- Record the exact command, count, duration, failures, skips, and material
  warnings truthfully.

---

## 23. Engineering Review Checklists

### Architecture review

- [ ] Responsibility belongs to the selected module owner.
- [ ] Existing extension points were evaluated before creating a new path.
- [ ] Dependencies point to stable contracts and are injected explicitly.
- [ ] Layer boundaries and architecture invariants remain intact.
- [ ] Planning and execution authority remain separated.
- [ ] Public compatibility and migration implications are documented.
- [ ] Lifecycle, health, events, logging, errors, and degraded behavior are defined.
- [ ] Security, data ownership, rollback, and recovery effects are reviewed.
- [ ] Test strategy covers determinism, concurrency, ordering, and failures as applicable.

### Code review

- [ ] Diff matches approved scope and contains no unrelated refactor.
- [ ] Names, types, docstrings, exceptions, and validation are clear.
- [ ] No hidden global, hardcoded provider, duplicated policy, or circular dependency was introduced.
- [ ] Models are immutable where required and inputs/outputs are validated.
- [ ] Logs/events avoid secrets and do not create command paths.
- [ ] Compatibility aliases and legacy behaviors remain covered.
- [ ] Tests assert behavior rather than implementation accidents.
- [ ] Documentation and comments state current truth without hype.
- [ ] Error and partial-failure paths fail safely.

### Sprint completion

- [ ] Approved objective and explicit non-goals are satisfied.
- [ ] Only approved files changed.
- [ ] Focused tests pass.
- [ ] Complete regression suite passes at or above the accepted baseline.
- [ ] Syntax/build and configured quality checks pass.
- [ ] `git diff --check` passes.
- [ ] Documentation and recovery records are synchronized.
- [ ] Working tree contains no accidental runtime artifacts.
- [ ] Risks, limitations, and follow-up work are reported.
- [ ] No commit, push, merge, or tag occurred without its separate approval.

### Release readiness

- [ ] Sprint completion checklist is complete.
- [ ] Compatibility and architecture reviews are approved.
- [ ] Changelog, version history, state, roadmap, and recovery checkpoints agree.
- [ ] Full suite result is recorded from the release candidate commit.
- [ ] Security and operational limitations are documented.
- [ ] Commit and branch are pushed and synchronized as authorized.
- [ ] Annotated tag name and target are verified.
- [ ] Upgrade, rollback, and recovery expectations are documented where relevant.
- [ ] Release claims describe implemented, verified behavior only.

---

## 24. Module Development Contract

Every future module must:

- Have one documented owner and responsibility not already covered elsewhere.
- Follow the allowed dependency direction in `SOFTWARE_ARCHITECTURE.md`.
- Define its public facade and keep concrete providers behind contracts.
- Follow the package responsibility model.
- Include complete docstrings.
- Include type hints.
- Remain independent and reusable.
- Integrate through abstractions where appropriate.
- Be covered by tests when behavior is significant.
- Be documented clearly.
- Preserve backward compatibility and established trust boundaries.
- Define validation, exception, lifecycle, health, logging, event, failure, and
  degraded-mode behavior where applicable.
- Pass architecture review before composition-root integration.

Future contributors are expected to verify repository truth, work within
approved scope, preserve existing work, provide evidence for quality claims,
and stop for renewed approval when a change would broaden authority or alter an
architecture invariant.

This guide is the engineering contract for the NARVIS project and must be
followed for all future development work.
