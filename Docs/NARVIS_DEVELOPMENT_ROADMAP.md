# NARVIS Development Roadmap

## Roadmap Purpose

This roadmap separates completed repository truth from future direction. Git history, source, and tests are authoritative.

## Current Checkpoint

- Version 1.4 is complete.
- Phases 1 through 13 are complete.
- Version 1.4 Milestones 1 through 3 are complete.
- Branch: `develop-v1.1`.
- Commit: `f5ffb5c`.
- Latest release tag: `v1.4-m3-sprint3`.
- Verified baseline: 1,052 passing tests.

## Completed Phase Table

| Phase | Primary outcome | Release checkpoint |
|---|---|---|
| 1 | Core architecture foundation | Complete |
| 2 | AI Brain foundation | Complete |
| 3 | Memory system | Complete |
| 4 | Dashboard and observability | Complete |
| 5 | Voice and vision foundations | Complete |
| 6 | Internet, desktop, and Evolution foundations | Complete |
| 7 | Recovery-bound mutation safety | Complete |
| 8 | Trusted Execution Gateway and controlled executors | Version 1.1 |
| 9 | Skill and planning-only Agent Frameworks | Version 1.2 |
| 10 | Computer and Desktop Integration | Version 1.2 |
| 11 | Safe Execution | Version 1.2 |
| 12 | Human Interaction and Conversation | Version 1.2 |
| 13 | AI Core, Routing, and Orchestrator | Version 1.3 |

## Version 1.4

Status: complete at `v1.4-m3-sprint3`.

### Milestone 1: Repository Professionalization

Status: complete. Tag: `v1.4-milestone1`.

- Synchronized repository state, architecture, roadmap, recovery, onboarding,
  contribution, and release-history documentation.
- Established architecture and engineering governance without changing runtime
  behavior, APIs, tests, or execution paths.

### Milestone 2: AI Runtime Integration

Status: complete.

| Sprint | Completed outcome | Tag |
|---:|---|---|
| 1 | AI Manager composition through existing DI, lifecycle, EventBus, and logging boundaries while preserving the BrainEngine path | `v1.4-m2-sprint1` |
| 2 | Passive built-in-provider compatibility adapters and deterministic fallback metadata | `v1.4-m2-sprint2` |
| 3 | Typed Conversation-AI runtime bridge with detached metadata and no execution edge | `v1.4-m2-sprint3` |

### Milestone 3: Runtime Observability

Status: complete.

| Sprint | Completed outcome | Tag |
|---:|---|---|
| 1 | Passive runtime diagnostics and deterministic metadata-only health | `v1.4-m3-sprint1` |
| 2 | Runtime Service Registry, dependency summaries, and aggregate compatibility health | `v1.4-m3-sprint2` |
| 3 | Runtime Capability Manifest and deterministic readiness reporting | `v1.4-m3-sprint3` |

All Version 1.4 observability surfaces remain passive. They do not resolve
services, call providers, probe the host or network, or create execution paths.

## Long-Term Direction

- Production hardening for AI, voice, vision, internet, and computer providers.
- Continued verification of permission, approval, execution, rollback, and audit boundaries.
- Deployment and operational readiness.
- Optional cloud or multi-instance capabilities only through injected providers and explicit security design.
- Broader capability integration only when deterministic behavior and backward compatibility can be preserved.

## Non-Goals

- Rewriting the architecture or refactoring completed phases.
- Replacing the legacy Brain, Skills, Computer, or runtime APIs.
- Allowing orchestration or planning models to execute directly.
- Weakening the Trusted Execution Gateway.
- Enabling autonomous Evolution or unrestricted host mutation.
- Treating roadmap direction as implemented capability.

## Roadmap Rules

- Work in small, independently verified sprints.
- Require explicit approval before mutation, commit, push, or tagging.
- Preserve immutable models, dependency injection, provider abstraction, EventBus integration, deterministic behavior, and compatibility.
- Add or update documentation and regression tests with every implementation sprint.
- Run focused tests, the full suite, applicable static checks, and `git diff --check` before completion.
