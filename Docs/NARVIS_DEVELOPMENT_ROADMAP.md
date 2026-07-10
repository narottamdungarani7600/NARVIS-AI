# NARVIS Development Roadmap

## Roadmap Purpose
This roadmap distinguishes current repository truth from future target capability. It is meant to help a fresh developer or a fresh Codex chat resume work in the correct order without assuming that planned features already exist.

## Current Checkpoint
- Branch: `develop-v1.1`
- Checkpoint commit: `ace8103044a2575053ed2285d5a29861cdbff19b`
- Current highest implemented Self-Evolution stage in the working tree: `Phase 5`
- Latest verified baseline: `294 tests`, `OK`

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

- Implemented in current working tree - Self-Evolution Phase 5
  - durable verification runs bound to exact granted execution authorizations
  - ordered verification step runs for `verification_observation` steps only
  - typed observation evidence records and truthful terminal outcomes
  - restart-safe verification journaling with no executor bridge

## Current Capability vs Future Target
Current capability:
- observe-only Self-Evolution
- capability discovery and evaluation
- approval recording
- deterministic plan creation
- typed execution-boundary request and authorization records
- typed verification-run, observation, and outcome records
- no mutation executor

Future target capability:
- NARVIS discovers useful capabilities
- NARVIS proposes a concrete change
- NARVIS asks the user for approval
- NARVIS executes only after a valid approval bound to the exact proposal revision
- NARVIS verifies results
- NARVIS records outcomes
- NARVIS recovers or rolls back on failure

## Future Phases In Dependency Order

### 1. Self-Evolution Phase 6 - Recovery And Rollback Execution Foundation
Status: next recommended phase

Goal:
- make rollback and recovery requirements durable, typed, and restart-safe without widening host mutation

Required outcome:
- typed rollback and recovery readiness records bound to exact approved verification state
- durable recovery journal
- explicit failure-handling and recovery-precondition reporting
- no uncontrolled executor

### 2. Self-Evolution Phase 7 - Narrow Approved Mutation Surfaces
Depends on: Phases 4 through 6

Initial mutation surfaces should be staged, not broad:
- software/package installation after explicit approval
- code execution after explicit approval
- source modification after explicit approval
- Git operations after explicit approval
- plugin/capability integration after explicit approval

Each surface should arrive only after:
- typed action boundary
- approval revalidation
- verification path
- recovery path

### 3. Self-Evolution Phase 8 - Broader Controlled Host And Application Actions
Depends on: earlier execution, verification, and rollback phases

Future targets:
- broad supported application/software control, not only one example application
- OS/computer control after explicit approval
- application control
- automation actions
- voice-driven control for supported workflows
- vision and screen understanding for supported workflows
- remote interaction and control through NARVIS

These remain future targets, not current capabilities.

### 4. Self-Evolution Phase 9 - Multi-Device And Remote Control Expansion
Depends on: earlier control safety phases

Long-term direction where technically supported:
- broad supported application/software and connected-device workflows
- computer control
- mobile interaction
- earbuds/watch/connected-device integration
- remote monitoring and remote action coordination

This is a long-term roadmap target and is not implemented today.

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

Every mutating phase after Phase 5 should preserve:
- exact proposal identity binding
- exact approval binding
- deterministic execution planning
- verification-before-trust
- explicit recovery requirements

Target end-to-end self-evolution flow:
- discover
- understand
- evaluate
- learn
- propose
- ask the user
- receive exact approval
- plan
- execute
- verify
- monitor
- recover or roll back
- remember outcome

## Verification, Recovery, Monitoring, And Rollback Direction
- Verification is now a first-class prerequisite before future execution.
- Recovery must exist before broad mutation surfaces are introduced.
- Monitoring and journaling must remain durable and restart-safe.
- Rollback should be explicit, typed, and bounded rather than informal prompt instructions.

## Long-Term Goals
These are target capabilities, not current repository claims:
- offline and online AI operation where the configured providers and local dependencies support it
- memory and conversational continuity across the supported runtime surfaces
- software/package installation after explicit approval
- code execution after explicit approval
- source modification after explicit approval
- Git operations after explicit approval
- plugin/capability integration after explicit approval
- OS/computer control after explicit approval
- application control
- broad supported application/software workflows rather than a single special-case application
- automation actions
- voice-driven control
- vision/screen understanding
- multi-device control across computer, mobile, earbuds, watch, and other connected devices where technically supported
- remote interaction and control through NARVIS
- self-evolution that discovers capabilities, proposes changes, asks the user, executes only after valid approval, verifies results, and recovers or rolls back on failure

## Roadmap Rules
- Do not describe roadmap targets as implemented features.
- Do not skip verification and recovery stages to reach broad mutation faster.
- Do not bypass typed action boundaries with ad hoc prompt instructions.
- Do not let documentation override repository truth.
