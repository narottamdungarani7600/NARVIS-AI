# Codex Recovery Prompt

Copy the prompt below into a completely new Codex chat when prior chat history is unavailable.

```text
You are recovering the NARVIS repository state from code and Git history only.

Important rules:
- Do not make code changes during recovery.
- Do not commit or push during recovery.
- Do not assume any prior Codex conversation exists.
- Repository code and Git history are the source of truth.
- Recovery documents are aids; verify them against actual code.

Recovery tasks:
1. Inspect the repository before making any change.
2. Read these recovery/navigation files if they exist:
   - README.md
   - Docs/NARVIS_PROJECT_STATE.md
   - Docs/NARVIS_DEVELOPMENT_ROADMAP.md
   - Docs/NARVIS_DECISIONS.md
   - Docs/CODEX_RECOVERY_PROMPT.md
   - Docs/RECOVERY_CHECKLIST.md
   - SOFTWARE_ARCHITECTURE.md
   - PROJECT_DEVELOPMENT_GUIDE.md
3. Inspect:
   - current branch
   - HEAD commit
   - git status --short --untracked-files=all
   - recent commits
   - narvis.py composition root
   - Core/execution/ trusted gateway
   - Core/diagnostics.py passive runtime diagnostics
   - Core/service_registry.py passive runtime service metadata
   - Core/capabilities.py runtime capability manifest and readiness
   - Execution/ sessions, previews, and coordinator
   - Conversation/ core, context, and lifecycle
   - AI/core/, AI/routing/, and AI/orchestrator/
   - AI/compatibility.py and AI/runtime.py
   - Memory/integration.py
   - Evolution/runtime.py
   - Internet/runtime.py
   - Skills/builtin.py
   - Computer/ package surfaces
   - Automation/ runtime surfaces
   - Voice/voice.py
   - Vision/vision.py
   - Dashboard/ service wiring
   - Core plugin/optimization surfaces
   - relevant tests, especially the runtime, Evolution, Execution,
     Conversation, AI Core, AI Routing, AI Orchestrator, AI integration,
     diagnostics, service-registry, and capability-manifest suites
4. Verify documentation claims against the actual repository.
5. Report any stale, conflicting, or exaggerated recovery information before proposing next work.
6. If the working tree is clean, run the baseline verification:
   - python -m unittest discover -s Tests -p "test_*.py"
   - git diff --check
   If the working tree is not clean, report that first and avoid destructive actions.
7. Summarize:
   - current project state
   - completed phases
   - current capabilities
   - missing capabilities
   - known degraded or null/default capabilities
   - exact next recommended development step
8. Make no code changes during recovery.
9. Make no commit or push during recovery.
10. Wait for explicit instruction after reporting.

Checkpoint expected when this prompt was last synchronized:
- Version 1.4 complete
- branch `develop-v1.1`
- HEAD `f5ffb5c`
- tag `v1.4-m3-sprint3`
- Phases 1 through 13 complete
- Milestone 1: Repository Professionalization complete
- Milestone 2: AI Runtime Integration complete
- Milestone 3: Runtime Observability complete
- 1,052 tests passing

Always verify these values from Git; do not assume they remain current.

Extra safety requirements:
- Check whether data/memory.sqlite3 is modified before assuming the tree is clean.
- Check whether tracked pycache artifacts such as AI/__pycache__/brain.cpython-313.pyc were dirtied by runtime/tests.
- Do not reset, restore, or discard user work unless explicitly instructed.
```
