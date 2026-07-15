# NARVIS Architectural Decision Ledger

This file is append-only. New entries should be added below the existing decisions instead of rewriting historical intent.

## NARVIS-DEC-001
Status: accepted

Context:
The project aims to move toward self-evolution and broader system control, but uncontrolled mutation would be unsafe and hard to verify.

Decision:
User approval is required before future mutating Self-Evolution actions.

Consequences:
- discovery and planning may exist before execution
- future mutation phases must include explicit approval checks
- the project does not treat capability discovery as implicit authorization

## NARVIS-DEC-002
Status: accepted

Context:
Approval text can become stale or ambiguous if it is not bound to exact proposal content.

Decision:
Approval must bind to an exact proposal revision and proposal fingerprint.

Consequences:
- approval for Proposal A cannot authorize Proposal B
- approval for an older proposal revision cannot authorize a revised proposal
- approval records must carry durable proposal identity

## NARVIS-DEC-003
Status: accepted

Context:
Proposal content can legitimately change after review.

Decision:
Revised proposals require fresh approval.

Consequences:
- old approvals expire when a new proposal fingerprint becomes current
- current proposal resolution must prefer the latest fingerprint
- future execution must revalidate approval against the current proposal revision

## NARVIS-DEC-004
Status: accepted

Context:
Planning records become hard to trust if the same semantic plan can produce different identifiers on rematerialization.

Decision:
Planning must be deterministic, including canonical plan fingerprinting that excludes volatile persistence fields.

Consequences:
- semantically identical rematerialized plans must hash the same way
- volatile timestamps and generated storage identifiers must not define plan identity
- tests must bypass persisted-plan reuse and verify canonical determinism directly

## NARVIS-DEC-005
Status: accepted

Context:
Execution without explicit verification and recovery requirements would increase the chance of silent regressions and unsafe mutation.

Decision:
Verification requirements and recovery requirements must exist before future execution phases.

Consequences:
- planning must record verification and recovery expectations explicitly
- later execution phases should consume typed verification and recovery records rather than inventing them ad hoc
- recovery is a prerequisite, not an afterthought

## NARVIS-DEC-006
Status: accepted

Context:
Evolution records are operational/project-control data, not ordinary user conversation memory.

Decision:
Evolution memory must remain isolated from generic conversational memory retrieval and summaries.

Consequences:
- discovery, evaluation, proposal, approval, journal, plan, and requirement records stay out of generic fallback recall
- explicit category retrieval remains available
- conversation continuity should not leak operational control records

## NARVIS-DEC-007
Status: accepted

Context:
Future broad control goals could be implemented unsafely if the system obeys natural language as direct mutation instructions.

Decision:
Future execution must use controlled typed action boundaries rather than arbitrary prompt obedience.

Consequences:
- future executors should operate on structured actions, not raw scraped or conversational text
- package install, source modify, git, plugin, OS, automation, and computer-control actions should each be typed and bounded
- approval should authorize explicit structured intent, not general free-form ambition

## NARVIS-DEC-008
Status: accepted

Context:
Grounded web research is useful for discovery, but public web content is noisy and can include malicious or irrelevant instructions.

Decision:
Discovered web content must never be treated directly as executable instruction.

Consequences:
- public web evidence can inform discovery/evaluation, but not act as an executor
- planning should preserve missing details instead of inventing executable commands from loose web evidence
- future mutation phases must require explicit internal normalization and approval, not scrape-and-run behavior

## NARVIS-DEC-009
Status: accepted

Context:
Large AI systems can overclaim capabilities if runtime facts are not checked against code and actual service wiring.

Decision:
Runtime truth is preferred over invented capability claims.

Consequences:
- composition-root behavior matters more than isolated unit assumptions
- documentation must be verified against actual runtime/service wiring
- recovery should inspect code, tests, branch, HEAD, and current status before making claims

## NARVIS-DEC-010
Status: accepted

Context:
The long-term project direction includes broad control and self-evolution, but implementing everything at once would collapse safety boundaries.

Decision:
Broad control remains a staged project goal and must be implemented in sequenced phases with verification and recovery.

Consequences:
- Self-Evolution Phase 4 and later should build execution capability incrementally
- remote control, multi-device control, package installation, source mutation, git mutation, and OS mutation should come later, not all at once
- each new control surface should inherit approval, verification, and rollback constraints

## NARVIS-DEC-011
Status: accepted

Context:
Phases 11 through 13 added Safe Execution, Conversation, and provider-agnostic
AI orchestration architecture while established runtime paths remained active.

Decision:
These packages are additive. `Execution/` does not bypass `Core/execution/`;
Conversation does not replace Memory; and `AI/core/`, `AI/routing/`, and
`AI/orchestrator/` do not replace the Brain. Immutable models, dependency
injection, provider abstraction, deterministic behavior, EventBus observability,
and compatibility aliases remain required. AI orchestration plans stay
unexecuted, and Version 1.4 work requires separately approved sprint scope.

Consequences:
- future integration extends existing composition and lifecycle boundaries
- plans, previews, routing results, and model output confer no execution authority
- backward compatibility and the Trusted Execution Gateway remain release gates
