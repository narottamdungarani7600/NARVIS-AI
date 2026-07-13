# NARVIS Development Roadmap

## Roadmap Purpose
This roadmap distinguishes current repository truth from future target capability. It is meant to help a fresh developer or a fresh Codex chat resume work in the correct order without assuming that planned features already exist.

## Current Checkpoint
- Branch: `develop-v1.1`
- Current HEAD: `500e248ee988d5829727c4c32a284e612b3e39ed`
- HEAD commit message: `Complete Phase 7-10 evolution and execution architecture`
- Preserved earlier migration checkpoint: `b48a11225f53a96d43f2164a7b41563081bbb8fb`
- Earlier checkpoint commit message: `Checkpoint before ChatGPT account migration: preserve Evolution and voice work`
- Current highest implemented Self-Evolution stage in the committed repository: `Phase 10`
- Phase 7 through 10 focused and runtime integration suites passed at the completion checkpoint. This documentation-only synchronization does not add a new full-suite result.

## Completed Phases
- Completed - Runtime and architecture foundation
  - stable application composition root
  - DI container and lifecycle wiring
  - Brain, Memory, Voice, Vision, Skills, Automation, Internet, Dashboard package integration

- Completed - Natural desktop control foundation
  - desktop control service
  - natural desktop command pipeline
  - universal open/application resolution

- Completed - Internet research foundation
  - public search with provider fallback
  - grounded research responses with sources
  - natural internet intent routing
  - safe multi-turn internet follow-up handling

- Completed - Structured live internet providers
  - live Wikipedia provider
  - live weather provider
  - live news provider
  - source-aware live news queries
  - conservative news quality, ranking, and follow-up improvements

- Completed - Memory continuity fixes
  - contextual research follow-up resolution
  - cross-session conversation-history isolation

- Completed - Self-Evolution Phase 1
  - capability inventory snapshot
  - discovery ledger
  - evidence-backed capability-gap detection

- Completed - Self-Evolution Phase 2
  - approval-controlled change proposals
  - exact proposal revision and fingerprint approval binding
  - durable approval journal

- Completed - Self-Evolution Phase 3
  - deterministic approved change planning
  - ordered plan steps
  - verification requirements
  - recovery requirements
  - durable restart-safe plan records

- Completed - Self-Evolution Phase 4
  - typed execution-step projection and executor-category classification
  - immutable execution requests bound to exact approved plans
  - immediate approval/plan revalidation before authorization
  - durable execution authorizations that prove no host action occurred

- Completed - Self-Evolution Phase 5
  - `create_verification_run()` creates durable verification runs bound to exact granted execution authorizations
  - `start_verification_step()` starts ordered `verification_observation` step runs only
  - `record_verification_observation()` persists typed verification evidence records
  - `complete_verification_step()` enforces evidence-backed step outcomes
  - `finalize_verification_run()` records truthful terminal outcomes
  - restart-safe verification journaling exists with no executor bridge

- Completed - Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation
  - typed, durable recovery and rollback-readiness records bound to exact verification state
  - restart-safe recovery journal, ordered recovery steps, observations, and truthful outcomes
  - recovery invalidation when exact bindings drift

- Completed - Self-Evolution Phase 7 - Narrow Approved Mutation Surfaces
  - typed mutation targets, approvals, runs, observations, outcomes, and rollback artifacts
  - deny-by-default mutation surface registry with protected core targets
  - pure guard validation for workspace paths, target kinds, risk levels, and protected surfaces
  - exact human mutation approval binding to proposal, run, targets, execution mode, and expiry
  - sequential placeholder mutation runs that stop on first failure

- Completed - Self-Evolution Phase 8 - Controlled Mutation Executor Simulations
  - typed sandbox, package, source, plugin, and Git executor services
  - strict target validation, protected-target rejection, and rollback metadata
  - explicit simulated executor selection through the Evolution runtime
  - no automatic or real host package, source, Git, plugin, network, or OS execution

- Completed - Self-Evolution Phase 9 - Planning Intelligence Pipeline
  - typed task planning with dependency support and deterministic execution plans
  - risk analysis, deterministic scheduling, workflow composition, and readiness decisions
  - runtime composition of the planning pipeline with `execution_allowed=False`
  - no automatic executor invocation or mutation

- Completed - Self-Evolution Phase 10 - Future Execution Simulation Framework
  - typed action registry and immutable execution-context snapshots
  - fail-closed execution validation for action registration, approval, recovery readiness, and protected targets
  - deterministic desktop, application, browser, and workflow simulation services
  - runtime dependency-injection registration and typed simulation APIs with no real host interaction

## Current Capability vs Future Target
Current capability:
- observe-only Self-Evolution through Phase 10
- capability discovery, evaluation, proposal approval, deterministic planning, typed authorization, verification, recovery, and rollback-readiness records
- deny-by-default mutation surface validation and exact human mutation approval
- explicit, typed mutation and controlled-executor simulations with rollback metadata
- deterministic planning intelligence that returns plans, risk assessments, schedules, workflows, and readiness decisions with execution disabled
- typed future-action context and validation with desktop, application, browser, and workflow simulations
- no autonomous or real runtime mutation, filesystem, package, Git, plugin, desktop, browser, network, or OS action

Future target capability:
- NARVIS discovers useful capabilities
- NARVIS proposes a concrete change
- NARVIS asks the user for approval
- NARVIS executes only after a valid approval bound to the exact proposal revision
- NARVIS verifies results
- NARVIS records outcomes
- NARVIS recovers or rolls back on failure

## Active Phase

### Self-Evolution Phase 11 - Scope Pending Explicit Design And Approval
Status: active planning checkpoint

Goal:
- establish the next narrow, approval-bound scope against the completed Phase 10 architecture without weakening current safety boundaries

Required conditions:
- preserve the proposal, approval, verification, recovery, mutation, planning, and future-action simulation flow
- preserve deny-by-default, fail-closed behavior and `observe_only` compatibility
- do not enable automatic execution or real host interaction without separate explicit approval
- define implementation, verification, recovery, and rollback effects before any code change

## Approval-Controlled Execution Goal
The long-term project goal is not generic autonomy. The goal is controlled, staged autonomy:
- discover
- evaluate
- propose
- ask
- approve
- execute only after valid approval
- verify
- recover or roll back if needed

Every mutating phase must preserve:
- exact proposal identity binding
- exact approval binding
- deterministic execution planning
- verification-before-trust
- explicit recovery requirements
- deny-by-default validation and protected-target restrictions
- no autonomous executor invocation

Target end-to-end self-evolution flow:
- discover
- understand
- evaluate
- learn
- propose
- ask the user
- receive exact approval
- plan
- execute only after explicit authorization
- verify
- monitor
- recover or roll back
- remember outcome

## Verification, Recovery, Monitoring, And Rollback Direction
- Verification is a first-class prerequisite before mutation paths are considered.
- Recovery and rollback readiness remain durable, exact-binding prerequisites for any approved mutation path.
- Monitoring and journaling must remain durable and restart-safe.
- Rollback must remain explicit, typed, and bounded rather than informal prompt instructions.
- Simulation results must never be represented as real host execution.

## Long-Term Goals
These are target capabilities, not current repository claims:
- offline and online AI operation where the configured providers and local dependencies support it
- memory and conversational continuity across the supported runtime surfaces
- approved real package, source, Git, and plugin operations only after a separately approved phase enables them
- approved OS/computer, application, browser, automation, voice, and vision workflows only after a separately approved phase enables them
- broad supported application/software workflows rather than a single special-case application
- multi-device control across computer, mobile, earbuds, watch, and other connected devices where technically supported
- remote interaction and control through NARVIS
- self-evolution that discovers capabilities, proposes changes, asks the user, executes only after valid approval, verifies results, and recovers or rolls back on failure

## Roadmap Rules
- Do not describe roadmap targets as implemented features.
- Do not skip verification and recovery stages to reach broad mutation faster.
- Do not bypass typed action boundaries with ad hoc prompt instructions.
- Do not let documentation override repository truth.
