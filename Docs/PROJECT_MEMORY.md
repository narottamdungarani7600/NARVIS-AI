# NARVIS Project Memory

## 1. Project Identity
NARVIS is a modular Python-based AI operating system/runtime for an advanced assistant platform. The repository is an active application, not a placeholder scaffold. It contains a real composition root, dependency-injected runtime services, deterministic tests, live internet providers, desktop-control capabilities, and staged Self-Evolution foundations.

Current repository policy treats code, tests, and Git state as authoritative if this document ever drifts.

## 2. Current Version
- Runtime config default: `1.0 Stable`
- Active development track: `develop-v1.1`

## 3. Current Development Phase
- Current highest implemented Self-Evolution stage: `Self-Evolution Phase 10 - Future Execution Simulation Framework`
- Current implementation remains `observe_only`; no autonomous mutation or host action is enabled.
- Phases 6 through 10 are implemented as typed, approval-bound, recovery-aware, fail-closed runtime capabilities. Their executor and future-action paths remain explicitly invoked and simulation-only at runtime.

## 4. Current Verified Baseline
- Baseline command: `python -m unittest`
- Phase 7 through 10 focused suites and runtime integration coverage passed at the committed Phase 10 completion checkpoint.
- This documentation-only synchronization does not record a new full-suite execution; rerun the baseline before future implementation work.
- Repository hygiene at synchronization start: clean working tree.

## 5. Repository Status
- Current branch: `develop-v1.1`
- Current HEAD: `500e248ee988d5829727c4c32a284e612b3e39ed`
- HEAD commit message: `Complete Phase 7-10 evolution and execution architecture`
- Preserved earlier migration checkpoint: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Working tree at the start of this documentation synchronization: clean.
- The Phase 7 through 10 implementation is committed in the current checkpoint; this documentation update is intentionally uncommitted pending approval.

## 6. Completed Phases
- `d01c487` - `NARVIS v0.9 Voice Engine`
- `5de44ee` - `NARVIS v1.0 Stable Release`
- `047eb92` - natural-language desktop command pipeline
- `856ef8e` - universal open system and website support
- `37e7975` - grounded web research with search-provider fallback
- `3e990e9` - Natural Internet Intent Routing
- `25cdab2` and `e607241` - live Wikipedia provider plus app wiring fix
- `46156f0` - live weather provider
- `ad3eecb`, `1c0bd67`, `16f4df4` - live news provider, source-aware news, and safe news follow-up improvements
- `73ab9bc` - contextual research follow-up and cross-session memory isolation
- `daf6d46` - Self-Evolution Phase 1: capability inventory and discovery ledger
- `6605717` - evolution capability classification alignment fix
- `3617235` - Self-Evolution Phase 2: approval-controlled proposals
- `4a87eb7` - Self-Evolution Phase 3: approval-bound deterministic change planning
- `ace8103` - Self-Evolution Phase 4: approval-revalidated typed execution boundary foundation
- `b48a11225f53a96d43f2164a7b41563081bbb8fb` - Self-Evolution Phase 5: verification lifecycle foundation
- `8e2802561978ff7b862d5f19dc64c51d5bbb83cb` - Self-Evolution Phase 6: recovery readiness foundation
- `500e248ee988d5829727c4c32a284e612b3e39ed` - Self-Evolution Phases 7 through 10: narrow mutation safety boundaries, controlled executor simulations, planning intelligence, and future execution simulation architecture

## 7. Current Architecture
`narvis.py` is the composition root. It builds and registers the runtime through dependency injection and lifecycle management.

Major architectural domains:
- `Core/` provides dependency injection, lifecycle management, plugins, logging, optimization, runtime coordination, and startup orchestration.
- `AI/` provides Brain orchestration, routing, intent analysis, provider-backed responses, and conversation continuity.
- `Memory/` provides SQLite-backed short-term, long-term, session, profile, search, and conversation-history services.
- `Computer/` provides desktop control, application resolution, clipboard, keyboard, mouse, screenshots, and window control.
- `Automation/` provides workspace-scoped automation helpers and queues.
- `Vision/` provides screenshot/camera capture, OCR, analysis, and safe degraded detector defaults.
- `Voice/` provides microphone, STT, TTS, wake-word, and voice-runtime services with truthful degraded behavior when dependencies are unavailable.
- `Internet/` provides grounded research, search fallback, live news/weather/Wikipedia providers, and null defaults for browser/download/YouTube.
- `Skills/` provides built-in skills and natural desktop command routing.
- `Dashboard/` provides runtime actions, log buffering, health display, and service wiring.
- `Evolution/` provides observe-only Self-Evolution through proposals, approval, planning, typed execution boundaries, verification, recovery readiness, narrow mutation guard and approval boundaries, simulated executor selection, planning intelligence, and typed future-action simulation.

## 8. Implemented Modules
- `AI/` - active
- `Assets/` - present
- `Automation/` - active with bounded scope
- `Computer/` - active
- `Config/` - present
- `Core/` - active
- `Dashboard/` - active
- `Docs/` - active, with Phase 10 completion synchronized in the continuity documents
- `Evolution/` - active through observe-only Phase 10
- `Internet/` - active with live research/news/weather/Wikipedia providers
- `Memory/` - active
- `Skills/` - active
- `Tests/` - active
- `Vision/` - active with degraded defaults
- `Voice/` - active with degraded defaults

## 9. Pending Modules
These are not fully implemented capability surfaces yet, even where placeholders or typed boundaries exist:
- browser-opening runtime beyond `NullBrowser`
- file-download runtime beyond `NullFileDownloader`
- YouTube provider beyond `NullYouTubeProvider`
- real mutation activation for package management, source changes, Git operations, plugin changes, OS mutation, desktop control mutation, browser interaction, and automation execution
- remote multi-device control expansion
- cloud integration beyond the current future hook registration

## 10. Current Safety Model
- Self-Evolution autonomy remains `observe_only`.
- Public web content is evidence, never executable instruction.
- The established proposal, approval, plan, authorization, verification, recovery, and rollback bindings remain mandatory before any explicit mutation simulation path.
- Phase 7 provides a deny-by-default mutation-surface registry, protected-target restrictions, guard validation, and exact human mutation approvals bound to proposal, run, target list, mode, and expiry.
- Phase 8 executor services are typed and selected only through explicit approved paths; the runtime performs simulations only and does not automatically invoke an executor. The isolated sandbox executor is intentionally blocked from runtime invocation because it can mutate only its dedicated sandbox filesystem.
- Phase 9 planning intelligence produces typed plans, risk assessments, schedules, workflows, and readiness decisions with `execution_allowed=False`.
- Phase 10 registers inert action records, immutable execution-context snapshots, fail-closed execution validation, and deterministic desktop, application, browser, and workflow simulations without OS, browser, network, package, Git, or host filesystem interaction.
- Verification and recovery readiness remain durable prerequisites, and recovery readiness is limited to `recovery_preparation` step participation only.
- Memory excludes Evolution control records from generic conversational retrieval and context summaries.
- Runtime truth from code, tests, and Git state is more important than remembered chat history or stale docs.

## 11. Current Approval Workflow
Current approved-control flow in the repository:
- discover candidate
- evaluate candidate
- create proposal
- record explicit approval decision
- create approval-bound deterministic plan
- create exact execution request
- authorize exact execution request after revalidation
- create exact verification run
- record verification observations and finalize truthful verification outcome
- create exact recovery run
- record recovery readiness observations and finalize truthful recovery outcome
- validate a requested mutation target against the deny-by-default surface registry
- record exact human `MutationApproval` before an explicit simulated mutation run
- optionally compose planning intelligence: request, plan, risk analysis, schedule, workflow, and readiness decision
- optionally compose future-action simulations: registered action, immutable context, validation, and deterministic executor/workflow result

Approval rules currently enforced by code and tests:
- approval is required before future mutating phases
- approval binds to the exact proposal revision and fingerprint
- revised proposals require fresh approval
- execution authorization is revalidated against the exact current proposal/plan/approval snapshot
- recovery readiness invalidates if verification state or exact bindings drift
- mutation approval rejects expired approvals, target mismatches, mode mismatches, protected targets, invalid target kinds, and paths outside the workspace
- no planning, mutation, executor, desktop, application, browser, or workflow service may execute automatically

## 12. Current Documentation List
Current documentation files visible in the local repository:
- `README.md`
- `CHANGELOG.md`
- `Docs/AI_DEVELOPMENT_RULES.md`
- `Docs/CODEX_RECOVERY_PROMPT.md`
- `Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md`
- `Docs/NARVIS_DECISIONS.md`
- `Docs/NARVIS_DEVELOPMENT_ROADMAP.md`
- `Docs/NARVIS_PROJECT_STATE.md`
- `Docs/PROJECT_MEMORY.md`
- `Docs/README.md` (present, currently empty)
- `Docs/RECOVERY_CHECKLIST.md`

Current documentation consistency status:
- `Docs/AI_DEVELOPMENT_RULES.md` is the permanent workflow and policy reference
- `Docs/PROJECT_MEMORY.md`, `Docs/NARVIS_PROJECT_STATE.md`, and `Docs/NARVIS_DEVELOPMENT_ROADMAP.md` record the committed Phase 10 checkpoint and should be reverified against code and Git before future changes.

## 13. Current Test Status
- The Phase 7 through 10 implementation checkpoint includes focused unit coverage for mutation services, controlled executor simulations, planning intelligence, future-action simulation services, and runtime integration.
- This documentation-only update did not rerun the full suite; run `python -m unittest` before the next substantive implementation or commit request.
- Key focused suites include:
  - `Tests.test_evolution_runtime`
  - `Tests.test_runtime_services`
  - `Tests.test_mutation_surfaces`
  - `Tests.test_mutation_policy`
  - `Tests.test_mutation_approval`
  - `Tests.test_mutation_runner`
  - `Tests.test_sandbox_executor`
  - `Tests.test_package_executor`
  - `Tests.test_source_executor`
  - `Tests.test_plugin_executor`
  - `Tests.test_git_executor`
  - `Tests.test_task_planner`
  - `Tests.test_risk_analyzer`
  - `Tests.test_execution_scheduler`
  - `Tests.test_workflow_engine`
  - `Tests.test_decision_engine`
  - `Tests.test_action_registry`
  - `Tests.test_execution_context`
  - `Tests.test_execution_validator`
  - `Tests.test_desktop_executor`
  - `Tests.test_application_executor`
  - `Tests.test_browser_executor`
  - `Tests.test_workflow_executor`
  - `Tests.test_internet_research`
  - `Tests.test_brain`
  - `Tests.test_voice`
- Phase 6 through 10 coverage includes recovery binding invalidation, mutation guard and approval rejection paths, sequential simulated run outcomes, executor target validation, deterministic planning/risk/scheduling/workflow/decision outputs, and runtime safety against host-action execution.

## 14. Known Limitations
- No runtime path enables autonomous or real host mutation.
- Runtime executor integration remains simulation-only; it cannot execute package installs, source modification, Git mutation, plugin mutation, automation execution, OS mutation, desktop interaction, application management, or browser interaction.
- The sandbox executor is deliberately not invoked by the runtime, even though its service is restricted to its configured sandbox directory.
- `NullBrowser`, `NullFileDownloader`, and `NullYouTubeProvider` remain placeholders.
- Voice depends on optional host/runtime dependencies such as `SpeechRecognition`, PocketSphinx, `PyAudio`, and `pyttsx3`.
- Vision remains partially degraded when OCR/detector dependencies are unavailable.

## 15. Roadmap
Current dependency order after the committed Phase 10 foundation:
- completed: Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation
- completed: Self-Evolution Phase 7 - Narrow Approved Mutation Surfaces
- completed: Self-Evolution Phase 8 - Controlled Mutation Executor Simulations
- completed: Self-Evolution Phase 9 - Planning Intelligence Pipeline
- completed: Self-Evolution Phase 10 - Future Execution Simulation Framework
- active: Self-Evolution Phase 11 - scope pending explicit design and approval

Long-term project direction remains:
- discover
- evaluate
- propose
- ask for approval
- plan
- execute only after valid approval
- verify
- recover or roll back if needed

## 16. Important Permanent Decisions
From the decision ledger and current implementation:
- user approval is required before future mutating Self-Evolution actions
- approval must bind to exact proposal identity
- revised proposals require fresh approval
- planning identity must be deterministic and exclude volatile fields
- verification and recovery requirements must exist before future execution phases
- mutation surfaces must remain deny-by-default, protected targets must remain blocked, and explicit human approval must bind exact mutation targets and mode
- all Phase 8 through 10 executor and future-action integrations must remain non-autonomous and simulation-only until a separately approved phase changes that boundary
- Evolution records must remain isolated from generic conversational memory
- future execution must use structured typed boundaries, not arbitrary prompt obedience
- discovered web content must never be treated as executable instruction
- repository truth overrides invented capability claims
- staged implementation order must be preserved

## 17. Things That Must Never Break
- `narvis.py` as the real composition root
- Natural Internet Intent Routing behavior
- grounded research provider fallback
- live Wikipedia, weather, and news providers
- contextual research follow-up and cross-session isolation
- exact proposal/approval/plan/request/authorization bindings
- verification lifecycle durability and truthful terminal outcomes
- Phase 6 recovery-readiness durability, invalidation rules, and non-executing safety boundary
- Phase 7 mutation guard, exact mutation approval, protected surface restrictions, and sequential failure-stop behavior
- Phase 8 through 10 explicit-only, fail-closed, simulation-only executor and future-action boundaries
- Evolution memory isolation from generic retrieval and summaries
- truthful degraded Voice and Vision behavior when optional dependencies are unavailable
- tracked artifact hygiene for `data/memory.sqlite3` and `AI/__pycache__/brain.cpython-313.pyc`

## 18. Startup Reading Order for Any AI Assistant
This section records the currently adopted startup order. The permanent rule lives in `Docs/AI_DEVELOPMENT_RULES.md`.

Use this order before making claims or recommendations:

1. `Docs/AI_DEVELOPMENT_RULES.md`
2. `Docs/PROJECT_MEMORY.md`
3. `Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md`
4. `Docs/NARVIS_PROJECT_STATE.md`
5. `Docs/NARVIS_DEVELOPMENT_ROADMAP.md`
6. `README.md`
7. `CHANGELOG.md`
8. `Docs/NARVIS_DECISIONS.md`
9. `Docs/CODEX_RECOVERY_PROMPT.md`
10. `Docs/RECOVERY_CHECKLIST.md`

Then verify against repository truth anchors:
- `narvis.py`
- `Evolution/runtime.py`
- `Evolution/models.py`
- `Memory/integration.py`
- `Internet/runtime.py`
- `Internet/research.py`
- `Skills/builtin.py`
- `Tests/test_evolution_runtime.py`
- `Tests/test_runtime_services.py`
- `Tests/test_internet_research.py`
- `Tests/test_brain.py`
- `Tests/test_voice.py`

Current repository policy is that prior AI chat history is not authoritative unless repository evidence confirms it.
