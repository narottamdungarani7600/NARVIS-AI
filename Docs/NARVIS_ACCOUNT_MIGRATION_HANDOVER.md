# NARVIS Account Migration Handover

## 1. Project Identity And Long-Term Vision
NARVIS is a modular Python-based AI operating system/runtime for an advanced assistant platform. The repository is not a placeholder scaffold; it is an active application with a real composition root, runtime subsystems, deterministic tests, live internet providers, desktop-control capabilities, and staged Self-Evolution foundations.

Long-term direction, derived from the current roadmap and decision ledger:
- keep NARVIS as a modular AI operating system with Brain, Memory, Voice, Vision, Internet, Skills, Automation, Desktop Control, Dashboard, and Self-Evolution domains;
- preserve a staged path from observe-only Self-Evolution to later approval-bound, verification-bound, and recovery-bound mutation phases;
- never treat discovered web content or free-form prompts as direct executable mutation instructions;
- keep recovery, rollback readiness, and explicit approval ahead of any future host mutation.

## 2. Current NARVIS Version And Architecture
- Runtime config default: `1.0 Stable`
- Active development track: `develop-v1.1`
- Current composition root: [`narvis.py`](/C:/Users/Sky/Desktop/NARVIS/narvis.py)
- Current branch at migration checkpoint: `develop-v1.1`
- Current HEAD / checkpoint commit: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Checkpoint commit message: `Checkpoint before ChatGPT account migration: preserve Evolution and voice work`

Architecture summary:
- `narvis.py` constructs the runtime through dependency injection and lifecycle-managed service registration.
- `AI/` provides Brain orchestration, routing, intent analysis, provider-backed responses, and multi-turn continuity.
- `Memory/` provides SQLite-backed short-term, long-term, session, profile, search, and conversation-history services.
- `Internet/` provides grounded research, live news/weather/Wikipedia, search-provider fallback, cache/history tracking, and safe internet routing seams.
- `Skills/` exposes the runtime behavior through built-in skills, including `internet.query` and desktop command skills.
- `Evolution/` provides observe-only phases 1 through 5: inventory, discovery/evaluation, proposal approval, deterministic planning, typed execution-boundary records, and verification/outcome journaling without host mutation.

## 3. Major Modules And Current Status
| Module | Current Status | Notes |
| --- | --- | --- |
| `Core/` | Active | Dependency injection, lifecycle, plugins, logging, optimization, runtime engine. |
| `AI/` | Active | Brain pipeline, routing, multi-turn continuity, contextual research/news follow-ups. |
| `Memory/` | Active | SQLite-backed memory with short-term, long-term, session, profile, conversation history, and Evolution isolation. |
| `Internet/` | Active | Grounded research plus live Google News RSS, Open-Meteo weather, and MediaWiki Wikipedia providers. |
| `Skills/` | Active | Built-in skills for internet, memory, help, status, desktop control, and desktop commands. |
| `Computer/` | Active | Windows-oriented application resolution, clipboard, keyboard, mouse, screenshots, window control. |
| `Automation/` | Active with bounded scope | Workspace-safe automation primitives and queues; no Self-Evolution execution bridge. |
| `Vision/` | Active with degraded defaults | Screenshot/image/OCR pipeline; optional detectors and camera availability depend on host/runtime dependencies. |
| `Voice/` | Active with degraded defaults | Voice runtime exists, degrades safely when optional audio/STT/TTS dependencies are unavailable, and is now wired to the app `process_text` path. |
| `Dashboard/` | Active | Runtime health/log/dashboard wiring exists. |
| `Evolution/` | Active observe-only foundation | Phases 1 through 5 are committed; no executor bridge, no package install, no git/source/OS mutation. |
| `Docs/` | Active but partially stale | Recovery docs are useful, but some checkpoint references still lag behind current HEAD and must be verified against `git` and code. |
| `Tests/` | Active | Full suite currently verified at `297 passing`, `0 failing`. |

## 4. Completed Development Phases
Completed and should not be repeated:
- `d01c487` - `NARVIS v0.9 Voice Engine`
- `5de44ee` - `NARVIS v1.0 Stable Release`
- `047eb92` - natural-language desktop command pipeline
- `856ef8e` - universal open system and website support
- `37e7975` - reliable grounded web research with search-provider fallback
- `3e990e9` - Natural Internet Intent Routing
- `25cdab2` and `e607241` - live Wikipedia provider plus app wiring fix
- `46156f0` - live weather provider
- `ad3eecb` - live news provider
- `1c0bd67` - source-aware live news queries
- `16f4df4` - live news quality and follow-up improvements
- `73ab9bc` - contextual research follow-up and cross-session memory isolation
- `daf6d46` - Self-Evolution Phase 1: capability inventory and discovery ledger
- `6605717` - evolution capability classification alignment fix
- `3617235` - Self-Evolution Phase 2: approval-controlled proposals
- `4a87eb7` - Self-Evolution Phase 3: approval-bound deterministic change planning
- `ace8103` - Self-Evolution Phase 4: approval-revalidated typed execution boundary foundation
- `b48a11225f53a96d43f2164a7b41563081bbb8fb` - migration checkpoint preserving the current Evolution and voice work, including the verified Phase 5 state and voice runtime wiring coverage

Current state distinction:
- Completed: all phases listed above.
- In progress: no uncommitted feature work is present in the working tree at the migration checkpoint.
- Future: Self-Evolution Phase 6 and later roadmap stages remain intentionally unimplemented.

## 5. Current Branch And Latest Checkpoint Commit Hash
- Branch: `develop-v1.1`
- HEAD: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Commit message: `Checkpoint before ChatGPT account migration: preserve Evolution and voice work`
- Remote state at handover baseline: local `develop-v1.1` was pushed to `origin/develop-v1.1`

## 6. Current Verified Test Status
- Verified full-suite status to preserve at migration handover: `297 passing`, `0 failing`
- Baseline full-suite command: `python -m unittest`
- Important focused suites:
  - `python -m unittest Tests.test_evolution_runtime`
  - `python -m unittest Tests.test_runtime_services Tests.test_internet_research Tests.test_brain`
  - `python -m unittest Tests.test_voice`
- Repository hygiene command used throughout recent work: `git diff --check`

## 7. Natural Internet Intent Routing Completion Status
Natural Internet Intent Routing is complete and should not be re-implemented.

Current completed behavior from the committed codebase:
- natural Hinglish/English internet research requests route through the existing skill/runtime path;
- grounded research uses public-web search with provider fallback;
- local/system/runtime identity requests are protected from accidental over-routing to Internet research;
- same-conversation follow-up internet context is preserved when appropriate and invalidated on unrelated routed actions;
- direct news turns publish canonical context so later follow-ups do not reuse stale earlier research topics;
- explicit contextual research follow-ups resolve the prior canonical subject instead of searching literal placeholders;
- cross-session conversation history leakage has already been fixed and should not be reopened without evidence.

Key reference files:
- [`AI/brain.py`](/C:/Users/Sky/Desktop/NARVIS/AI/brain.py)
- [`Internet/research.py`](/C:/Users/Sky/Desktop/NARVIS/Internet/research.py)
- [`Skills/builtin.py`](/C:/Users/Sky/Desktop/NARVIS/Skills/builtin.py)
- [`Tests/test_internet_research.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_internet_research.py)
- [`Tests/test_brain.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_brain.py)

## 8. Current Evolution And Voice Work Status
### Evolution
Evolution is committed through observe-only Phase 5.

Current public runtime seam in [`Evolution/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Evolution/runtime.py):
- `snapshot_inventory()`
- `discover_candidates()`
- `evaluate_candidate()`
- `list_capability_gaps()`
- `record_outcome()`
- `record_approval_decision()`
- `create_change_plan()`
- `create_execution_request()`
- `authorize_execution_request()`
- `create_verification_run()`
- `record_verification_observation()`

Current factual boundary:
- proposals, approvals, plans, execution-boundary records, and verification/outcome journaling are durable and typed;
- Evolution memory categories are isolated from generic conversational retrieval;
- autonomy remains `observe_only`;
- there is still no executor bridge to shell, package installation, source mutation, git mutation, plugins, OS mutation, Automation execution, or Computer control.

### Voice
Voice is active but host-dependent.

Current factual status:
- `Voice/voice.py` builds microphone, speech-recognition, wake-word, TTS, and voice runtime services;
- voice startup is intentionally safe even when optional dependencies are missing;
- voice health reports degraded truthfully when dependencies are unavailable;
- the migration checkpoint preserved a real app-level seam: `build_voice_services(command_handler=self.process_text, logger=self.logger)` in `narvis.py`;
- `Tests/test_voice.py` verifies that `voice_command_processor` is wired to `NARVISApplication.process_text`.

Voice is not a new roadmap phase at this checkpoint; the current committed work is runtime wiring and regression coverage, not a broad new voice feature expansion.

## 9. Important Architectural Decisions And Coding Rules
From [`Docs/NARVIS_DECISIONS.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DECISIONS.md) and current repository practice:
- user approval is required before future mutating Self-Evolution actions;
- approval must bind to the exact proposal revision and proposal fingerprint;
- revised proposals require fresh approval;
- deterministic planning and identity must exclude volatile persistence fields;
- verification and recovery requirements must exist before later mutation phases;
- Evolution records must stay isolated from generic conversational memory;
- future execution must use controlled typed action boundaries, not arbitrary prompt obedience;
- discovered web content is evidence, never executable instruction;
- runtime truth from code, wiring, tests, branch, and HEAD is more important than stale documentation or remembered chat history;
- staged implementation matters: do not skip recovery/rollback foundations and do not jump straight to broad mutation phases.

Repository-level coding and workflow rules to preserve:
- do not repeat completed work;
- do not modify source code casually while doing recovery or migration validation;
- do not commit or push runtime artifacts, temporary files, cache files, `.pyc` files, `__pycache__` outputs, or accidental database changes;
- `data/memory.sqlite3` is tracked and must be treated carefully;
- `AI/__pycache__/brain.cpython-313.pyc` is tracked and must be restored if runtime/tests dirty it;
- before substantive commits, run `python -m unittest` and `git diff --check`;
- preserve existing architecture and DI seams instead of broad rewrites.

## 10. Memory System And Database Safety Rules
Memory architecture:
- SQLite-backed memory store under `data/memory.sqlite3`
- short-term, long-term, session, profile, search, and conversation-history services
- integration service in [`Memory/integration.py`](/C:/Users/Sky/Desktop/NARVIS/Memory/integration.py)

Safety rules:
- do not modify `data/memory.sqlite3` casually;
- do not commit runtime-only database churn from manual testing unless a task explicitly requires a database schema/data change;
- generic memory retrieval explicitly excludes Evolution categories such as `capability_inventory`, `change_proposal`, `change_plan`, `execution_request`, `verification_run`, and related records;
- preserve short-term, long-term, profile, session, and same-conversation behavior when touching memory code;
- preserve cross-session isolation and do not allow conversation-history fallback leakage to reappear.

## 11. Internet Research Architecture And Provider Fallback Behavior
Current runtime wiring in [`Internet/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Internet/runtime.py):
- shared HTTP seam: `BaseHttpClient` with default `UrllibHttpClient`
- search provider chain: `build_public_search_provider_chain()`
- grounded research service: `InternetResearchService`
- live providers:
  - `GoogleNewsRssProvider`
  - `OpenMeteoWeatherProvider`
  - `MediaWikiWikipediaProvider`
- non-live placeholders:
  - `NullBrowser`
  - `NullFileDownloader`
  - `NullYouTubeProvider`

Grounded research behavior:
- public search provider chain uses DuckDuckGo HTML first and Bing HTML fallback;
- research uses `SafePageFetcher` plus provider-backed synthesis with a deterministic fallback synthesizer;
- internet/news follow-up handling is already integrated through the existing skill path and Brain context lifecycle;
- structured providers keep network access behind the current HTTP abstraction;
- cache/history normalization already exists for news and internet operations and should be preserved.

## 12. Current Known Limitations Or Pending Work
Completed work must not be repeated, but these truthful limitations remain:
- Self-Evolution is still `observe_only`; there is no executor bridge.
- No package installation, arbitrary code execution, source self-modification, git mutation, plugin installation, OS mutation, Automation execution, or Computer-control mutation is allowed from Evolution.
- `NullBrowser`, `NullFileDownloader`, and `NullYouTubeProvider` remain placeholders.
- Voice depends on optional host/runtime dependencies such as `SpeechRecognition`, `PyAudio`, and `pyttsx3`.
- Vision still uses degraded defaults when optional OCR/detector dependencies are unavailable.
- Some recovery docs lag behind current HEAD:
  - [`Docs/NARVIS_PROJECT_STATE.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_PROJECT_STATE.md) still references checkpoint `ace8103...` and `294 tests`.
  - [`Docs/NARVIS_DEVELOPMENT_ROADMAP.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DEVELOPMENT_ROADMAP.md) still describes Phase 5 as working-tree state rather than fully preserved in the migration checkpoint.
- Because of those stale references, future recovery must verify against `git`, `README.md`, `CHANGELOG.md`, `narvis.py`, and tests before making claims.

## 13. Exact Next Recommended Development Phase
Recommended next phase:

`Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation`

Why this is next:
- the current repository already has typed proposals, approvals, deterministic plans, execution-boundary records, and verification journaling;
- the roadmap and decision ledger both require recovery and rollback readiness before any later mutation or execution phase;
- Phase 6 preserves the project safety model by making rollback/readiness durable before widening control surfaces.

What it should do, based on current roadmap/project-state truth:
- turn recovery requirements into typed, durable rollback/readiness records;
- preserve exact bindings across proposal, approval, plan, execution request, authorization, and verification identity;
- remain non-executing until rollback semantics are explicit, restart-safe, and fully verified.

What it should not do:
- do not start broad execution/mutation surfaces yet;
- do not skip recovery and jump directly to installs, source mutation, git mutation, or OS actions.

## 14. Important Files The Next Codex Account Should Read First
Read these first, in roughly this order:
- [`Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md)
- [`README.md`](/C:/Users/Sky/Desktop/NARVIS/README.md)
- [`CHANGELOG.md`](/C:/Users/Sky/Desktop/NARVIS/CHANGELOG.md)
- [`Docs/NARVIS_PROJECT_STATE.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_PROJECT_STATE.md)
- [`Docs/NARVIS_DEVELOPMENT_ROADMAP.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DEVELOPMENT_ROADMAP.md)
- [`Docs/NARVIS_DECISIONS.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DECISIONS.md)
- [`Docs/CODEX_RECOVERY_PROMPT.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/CODEX_RECOVERY_PROMPT.md)
- [`Docs/RECOVERY_CHECKLIST.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/RECOVERY_CHECKLIST.md)
- [`narvis.py`](/C:/Users/Sky/Desktop/NARVIS/narvis.py)
- [`Evolution/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Evolution/runtime.py)
- [`Internet/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Internet/runtime.py)
- [`AI/brain.py`](/C:/Users/Sky/Desktop/NARVIS/AI/brain.py)
- [`Skills/builtin.py`](/C:/Users/Sky/Desktop/NARVIS/Skills/builtin.py)
- [`Memory/integration.py`](/C:/Users/Sky/Desktop/NARVIS/Memory/integration.py)
- [`Tests/test_evolution_runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_evolution_runtime.py)
- [`Tests/test_runtime_services.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_runtime_services.py)
- [`Tests/test_internet_research.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_internet_research.py)
- [`Tests/test_voice.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_voice.py)
- [`Tests/test_brain.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_brain.py)

## 15. Git Workflow And Branch Rules
- Stay on `develop-v1.1` unless an explicit instruction says otherwise.
- The migration checkpoint commit to preserve is exactly `b48a11225f53a96d43f2164a7b41563081bbb8fb`.
- Do not create a new branch just to resume normal work unless explicitly requested.
- Check before doing anything:
  - `git branch --show-current`
  - `git rev-parse HEAD`
  - `git status --short --untracked-files=all`
  - `git log --oneline -12`
- Review diffs before any restore/reset/cleanup.
- Never discard uncommitted work you did not create.
- Stage only intended source/doc/test files.
- Do not commit:
  - `data/memory.sqlite3`
  - tracked/generated `AI/__pycache__/brain.cpython-313.pyc`
  - other `.pyc`, `__pycache__`, cache, temp, runtime, or manual-test artifacts
- Before a final commit on substantive work, run:
  - `python -m unittest`
  - `git diff --check`

## 16. Environment / Setup Requirements Needed To Continue Development
- Platform assumptions in current code: Windows-oriented desktop control and application resolution are first-class.
- Python environment: current repo uses [`requirements.txt`](/C:/Users/Sky/Desktop/NARVIS/requirements.txt); no `pyproject.toml` is present.
- Required baseline dependency listed:
  - `python-dotenv`
- Optional voice dependencies listed:
  - `SpeechRecognition`
  - `PyAudio`
  - `pyttsx3`
- Optional AI provider SDKs are commented out in `requirements.txt`; current runtime can still degrade/fallback when API keys or SDKs are unavailable.
- Optional voice/vision host tools may still be needed for full real-machine capability:
  - microphone/audio stack for live voice
  - PocketSphinx / SpeechRecognition for offline STT paths
  - Tesseract or other OCR dependencies for fuller vision behavior
- Baseline continuation checks on a fresh machine/account:
  - verify branch/HEAD/status
  - run `python -m unittest`
  - run `git diff --check`
  - verify no runtime artifacts were accidentally created/staged

## 17. New Codex Account Startup Instructions
Exact startup order before any code change:

1. Confirm repository state:
   - `git branch --show-current`
   - `git rev-parse HEAD`
   - `git status --short --untracked-files=all`
   - `git log --oneline -12`
2. Read this handover file first:
   - [`Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_ACCOUNT_MIGRATION_HANDOVER.md)
3. Read repository continuity docs:
   - [`README.md`](/C:/Users/Sky/Desktop/NARVIS/README.md)
   - [`CHANGELOG.md`](/C:/Users/Sky/Desktop/NARVIS/CHANGELOG.md)
   - [`Docs/NARVIS_PROJECT_STATE.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_PROJECT_STATE.md)
   - [`Docs/NARVIS_DEVELOPMENT_ROADMAP.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DEVELOPMENT_ROADMAP.md)
   - [`Docs/NARVIS_DECISIONS.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/NARVIS_DECISIONS.md)
   - [`Docs/CODEX_RECOVERY_PROMPT.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/CODEX_RECOVERY_PROMPT.md)
   - [`Docs/RECOVERY_CHECKLIST.md`](/C:/Users/Sky/Desktop/NARVIS/Docs/RECOVERY_CHECKLIST.md)
4. Verify docs against code, with these files as truth anchors:
   - [`narvis.py`](/C:/Users/Sky/Desktop/NARVIS/narvis.py)
   - [`Evolution/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Evolution/runtime.py)
   - [`Internet/runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Internet/runtime.py)
   - [`AI/brain.py`](/C:/Users/Sky/Desktop/NARVIS/AI/brain.py)
   - [`Skills/builtin.py`](/C:/Users/Sky/Desktop/NARVIS/Skills/builtin.py)
   - [`Memory/integration.py`](/C:/Users/Sky/Desktop/NARVIS/Memory/integration.py)
5. Read the key regression suites:
   - [`Tests/test_evolution_runtime.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_evolution_runtime.py)
   - [`Tests/test_runtime_services.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_runtime_services.py)
   - [`Tests/test_internet_research.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_internet_research.py)
   - [`Tests/test_voice.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_voice.py)
   - [`Tests/test_brain.py`](/C:/Users/Sky/Desktop/NARVIS/Tests/test_brain.py)
6. Explicitly note what is already complete and must not be repeated:
   - Natural Internet Intent Routing
   - grounded research fallback
   - live Wikipedia/weather/news
   - source-aware and follow-up-safe news handling
   - contextual research follow-up and cross-session isolation
   - Self-Evolution phases 1 through 5
   - current voice runtime wiring checkpoint
7. If the working tree is clean, run:
   - `python -m unittest`
   - `git diff --check`
8. Only after the repository state is understood, propose the next task:
   - `Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation`
9. Do not start any new feature or code change until steps 1 through 8 are complete.

## Final Migration Reminder
This handover is intended to prevent duplicated work. The next account should treat completed phases as done unless code or tests prove otherwise. When in doubt, trust the current repository, Git history, runtime wiring, and regression tests over remembered chat history.
