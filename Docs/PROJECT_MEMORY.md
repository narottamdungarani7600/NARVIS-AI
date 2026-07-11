# NARVIS Project Memory

## 1. Project Identity
NARVIS is a modular Python-based AI operating system/runtime for an advanced assistant platform. The repository is an active application, not a placeholder scaffold. It contains a real composition root, dependency-injected runtime services, deterministic tests, live internet providers, desktop-control capabilities, and staged Self-Evolution foundations.

Current repository policy treats code, tests, and Git state as authoritative if this document ever drifts.

## 2. Current Version
- Runtime config default: `1.0 Stable`
- Active development track: `develop-v1.1`

## 3. Current Development Phase
- Current highest implemented Self-Evolution stage: `Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation`
- Current implementation remains `observe_only`
- Phase 6 is implemented as a typed, durable, restart-safe, non-executing recovery-readiness lifecycle

## 4. Current Verified Baseline
- Baseline command: `python -m unittest`
- Latest locally verified result: `306 passing`, `0 failing`
- Repository hygiene check: `git diff --check` passes on the current working tree

## 5. Repository Status
- Current branch: `develop-v1.1`
- Current HEAD: `8e2802561978ff7b862d5f19dc64c51d5bbb83cb`
- HEAD commit message: `Implement Self-Evolution Phase 6 recovery readiness foundation`
- Preserved earlier migration checkpoint: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Working tree snapshot at the last project-memory refresh:
  - `?? Docs/AI_DEVELOPMENT_RULES.md`
  - `?? Docs/PROJECT_MEMORY.md`
- Some continuity documents remain behind current HEAD and should be reverified against code and Git before reuse

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
- `Evolution/` provides observe-only Self-Evolution through proposals, approval, planning, typed execution boundaries, verification, and recovery readiness.

## 8. Implemented Modules
- `AI/` - active
- `Assets/` - present
- `Automation/` - active with bounded scope
- `Computer/` - active
- `Config/` - present
- `Core/` - active
- `Dashboard/` - active
- `Docs/` - active, but some continuity docs are stale relative to current HEAD
- `Evolution/` - active through observe-only Phase 6
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
- broad mutation executor surfaces for package management, code changes, Git operations, plugin changes, OS mutation, computer control mutation, and automation execution
- remote multi-device control expansion
- cloud integration beyond the current future hook registration

## 10. Current Safety Model
- Self-Evolution autonomy remains `observe_only`.
- Public web content is evidence, never executable instruction.
- Typed boundaries exist for future execution categories, but no mutation executor bridge is active.
- Verification and recovery readiness are durable prerequisites ahead of any future mutation phases.
- Phase 6 remains strictly non-executing.
- Recovery readiness is limited to `recovery_preparation` step participation only.
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

Approval rules currently enforced by code and tests:
- approval is required before future mutating phases
- approval binds to the exact proposal revision and fingerprint
- revised proposals require fresh approval
- execution authorization is revalidated against the exact current proposal/plan/approval snapshot
- recovery readiness invalidates if verification state or exact bindings drift

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
- Some continuity documents remain behind current HEAD and should be synchronized before being used as authoritative status snapshots

## 13. Current Test Status
- Full suite verified locally: `306 passing`, `0 failing`
- Key focused suites include:
  - `Tests.test_evolution_runtime`
  - `Tests.test_runtime_services`
  - `Tests.test_internet_research`
  - `Tests.test_brain`
  - `Tests.test_voice`
- Current Phase 6 coverage includes:
  - idempotent recovery run creation
  - recovery step lifecycle
  - recovery observation durability
  - recovery invalidation on binding drift
  - recovery memory isolation
  - application-level safety against host-action execution

## 14. Known Limitations
- No mutation executor bridge exists.
- Self-Evolution cannot execute package installs, source modification, Git mutation, plugin mutation, automation execution, OS mutation, or desktop mutation.
- `NullBrowser`, `NullFileDownloader`, and `NullYouTubeProvider` remain placeholders.
- Voice depends on optional host/runtime dependencies such as `SpeechRecognition`, PocketSphinx, `PyAudio`, and `pyttsx3`.
- Vision remains partially degraded when OCR/detector dependencies are unavailable.
- Some continuity docs are stale relative to current code and Git state.

## 15. Roadmap
Current dependency order after the implemented Phase 6 foundation:
- completed: Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation
- next: Self-Evolution Phase 7 - Narrow Approved Mutation Surfaces
- later: Self-Evolution Phase 8 - Broader Controlled Host And Application Actions
- later: Self-Evolution Phase 9 - Multi-Device And Remote Control Expansion

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
