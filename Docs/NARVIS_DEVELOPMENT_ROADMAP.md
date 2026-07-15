# NARVIS Development Roadmap

## Roadmap Purpose

This roadmap separates completed repository truth from future direction. Git history, source, and tests are authoritative.

## Current Checkpoint

- Version 1.3 is complete.
- Phases 1 through 13 are complete.
- Branch: `develop-v1.1`.
- Commit: `e50453f`.
- Latest tag: `v1.3-phase13-sprint3`.
- Verified baseline: 994 passing tests.

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

### Milestone 1: Repository and Integration Readiness

#### Sprint 1: Repository State Synchronization

Status: active documentation milestone.

Scope:

- synchronize version, phase, architecture, health, recovery, onboarding, and roadmap documentation;
- record the 994-test baseline and Version 1.3 checkpoint;
- define Version 1.4 direction and non-goals without changing runtime behavior.

#### Recommended Future Sprints

These are planning recommendations, not implementation authorization:

1. Additive composition of the Phase 13 AI manager through existing dependency injection and lifecycle boundaries while preserving the Brain path.
2. Production-provider adapter hardening with deterministic routing, explicit capability metadata, safe fallback, and network-free tests.
3. Typed conversation-aware orchestration integration without duplicating context ownership or enabling plan execution.

Exact scope, files, compatibility impact, and verification must be approved before each sprint.

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
