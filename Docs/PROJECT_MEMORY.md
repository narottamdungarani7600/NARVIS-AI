# NARVIS Project Memory

## Current Truth

- Product: NARVIS AI Operating System.
- Current completed version: 1.4.
- Branch: `develop-v1.1`.
- Checkpoint commit: `f5ffb5c`.
- Latest release tag: `v1.4-m3-sprint3`.
- Completed product phases: 1 through 13.
- Milestone 1: Repository Professionalization is complete.
- Milestone 2: AI Runtime Integration is complete.
- Milestone 3: Runtime Observability is complete.
- Verified test baseline: 1,052 passing tests.

Git history, source, and tests override this continuity note.

## Architecture Memory

- `narvis.py` remains the application composition root.
- Core provides dependency injection, lifecycle management, EventBus, plugins,
  structured logging, health, startup, and the Trusted Execution Gateway.
- The legacy Brain, Skills, Computer, and runtime APIs remain supported.
- Phase 9 added typed Skills and planning-only Agents.
- Phase 10 added provider-backed computer information and desktop inspection.
- Phase 11 added execution sessions, previews, risk/readiness, state, and
  coordination without bypassing `Core/execution/`.
- Phase 12 added immutable Conversation core, context, and lifecycle services.
- Phase 13 added provider-agnostic AI Core, deterministic Routing, and
  non-executing Orchestrator sessions and plans.
- Version 1.4 composed the AI Manager, added passive provider compatibility
  adapters and a typed Conversation-AI bridge, and introduced immutable runtime
  diagnostics, service-registry, capability-manifest, and readiness surfaces.
- Evolution remains observe-only, explicit, and fail-closed.

## Permanent Guarantees

- Preserve immutable typed models.
- Preserve constructor injection, provider abstraction, and EventBus behavior.
- Preserve deterministic ordering and injectable clocks/IDs in tests.
- Preserve public APIs and compatibility aliases.
- Keep AI/Agent planning separate from host execution.
- Keep Safe Execution subordinate to the Trusted Execution Gateway.
- Keep permission, risk, approval, verification, rollback, and audit bindings.
- Never treat web or model output as executable instruction.
- Never mutate, commit, push, or tag without the required explicit approval.

## Version History

| Version | Product phases or milestones | Outcome |
|---|---|---|
| 1.1 | 1-8 | Stable modular foundation and Trusted Execution Gateway |
| 1.2 | 9-12 | Skills/Agents, Computer/Desktop, Safe Execution, Conversation |
| 1.3 | 13 | AI Core, AI Routing, AI Orchestrator |
| 1.4 | Milestones 1-3 | Repository Professionalization, AI Runtime Integration, Runtime Observability |

## Known Degraded Capabilities

- AI providers may fall back when credentials or remote calls are unavailable.
- Voice depends on optional STT/TTS libraries and audio hardware.
- Vision depends on optional OCR/detection libraries and camera hardware.
- Browser, downloader, and YouTube integrations may use safe null providers.
- No unrestricted autonomous host execution or remote multi-device control is implemented.

## Recovery Sequence

1. Read `Docs/AI_DEVELOPMENT_RULES.md`.
2. Verify branch, HEAD, tag, status, and recent Git history.
3. Read this file, the handover, project state, roadmap, README, changelog,
   architecture, decisions, recovery prompt, and checklist.
4. Inspect `narvis.py` and the relevant package/test surfaces, especially
   `Execution/`, `Conversation/`, `AI/core/`, `AI/routing/`, and
   `AI/orchestrator/`, `AI/compatibility.py`, `AI/runtime.py`,
   `Core/diagnostics.py`, `Core/service_registry.py`, and
   `Core/capabilities.py` for the latest phases and milestones.
5. Run focused tests as appropriate, then the complete 1,052-test baseline and
   `git diff --check`.
6. Report discrepancies and wait for explicit approval before mutation.

## Version 1.4 Release Boundary

Version 1.4 is complete. Its AI compatibility and observability surfaces are
passive or architecture-only: they do not execute providers, plans, network
calls, service factories, health probes, or host actions. Post-release work
must not rewrite the architecture, remove compatibility, execute plans
directly, weaken trust boundaries, or enable autonomous Evolution.
