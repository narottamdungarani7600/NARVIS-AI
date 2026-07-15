# Contributing to NARVIS

Contributions should extend the existing modular architecture while preserving
deterministic behavior, compatibility, observability, and execution safety.

## Repository Baseline

| Field | Value |
|---|---|
| Completed version | Version 1.4 |
| Completed phases | 1 through 13 |
| Completed milestones | Milestone 1: Repository Professionalization; Milestone 2: AI Runtime Integration; Milestone 3: Runtime Observability |
| Development branch | `develop-v1.1` |
| Latest release tag | `v1.4-m3-sprint3` |
| Full-suite baseline | 1,052 passing tests |

Verify these values from Git before relying on them.

## Before Contributing

1. Read [Docs/README.md](Docs/README.md).
2. Review the current project state and roadmap.
3. Read [SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md) and
   [PROJECT_DEVELOPMENT_GUIDE.md](PROJECT_DEVELOPMENT_GUIDE.md).
4. Inspect the source and tests for the relevant subsystem.
5. Confirm branch, HEAD, status, and recent history.
6. Agree on a focused scope before starting substantive work.

Do not assume that a roadmap item is implemented or that a prior conversation
accurately describes the checkout.

## Local Setup

```powershell
git checkout develop-v1.1
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s Tests -p "test_*.py"
```

Python 3.10+ is required. Optional voice, vision, device, and remote-provider
features may require additional local dependencies, hardware, or credentials.

## Contribution Principles

- Keep changes small, cohesive, and within approved scope.
- Extend existing abstractions instead of creating parallel runtime paths.
- Preserve public APIs, compatibility aliases, established command forms, and
  completed-module behavior.
- Use immutable typed models and injected dependencies at established
  boundaries.
- Preserve provider abstraction, lifecycle management, EventBus behavior,
  structured logging, and deterministic ordering.
- Keep planning, routing, negotiation, and preview records separate from
  execution authority.
- Never bypass the Trusted Execution Gateway or weaken approval, verification,
  rollback, or audit guarantees.
- Do not execute public web content or model output as instructions.
- Avoid unrelated cleanup and refactoring.

## Contributor Architecture Contract

Before creating or relocating a module, identify its owner, responsibility,
public facade, dependencies, provider boundary, lifecycle, failure behavior,
tests, and documentation. A new module is justified only when an existing owner
or extension point cannot represent the responsibility cleanly.

Contributors must preserve these invariants:

- composition remains explicit through `narvis.py` and injected services;
- dependencies point toward contracts rather than concrete providers;
- domain ownership is not duplicated across packages;
- planning and execution authority remain separate;
- public compatibility surfaces remain available within the release line;
- events and logs observe behavior without becoming command channels;
- host-capable actions remain behind trusted execution controls.

The complete ownership matrix and dependency policy are in
[SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md).

## Code and Documentation Standards

- Use Python 3.10+ syntax, type hints, clear public docstrings, four-space
  indentation, and readable PEP 8-oriented formatting.
- Keep packages focused on their documented responsibilities.
- Add deterministic success, failure, validation, and compatibility tests for
  behavior changes.
- Update public, architecture, state, roadmap, changelog, and recovery
  documentation when their claims change.
- Clearly label proposed/future capabilities; never describe them as implemented.
- Do not remove tests or reduce the verified baseline to accommodate a change.

## Testing and Validation

Run a focused suite while iterating:

```powershell
python -m unittest Tests.test_ai_orchestrator
```

Before review, run:

```powershell
python -m unittest discover -s Tests -p "test_*.py"
git diff --check
git status --short --untracked-files=all
```

Inspect memory databases, bytecode, logs, screenshots, and temporary directories
before staging. The repository currently has no checked-in Ruff, Black,
Flake8, Pylint, or mypy configuration, so report only checks actually run.

## Git Workflow

1. Start from the approved branch and verify the working tree.
2. Preserve pre-existing changes and avoid destructive cleanup.
3. Review `git diff`, `git diff --stat`, and `git diff --check`.
4. Stage only intended files after validation.
5. Use a focused commit message naming the phase, sprint, fix, or documentation
   milestone.
6. Treat commit, push, and tag as separate approval gates.
7. Never force-push shared history or move published tags.

Do not commit generated artifacts, secrets, credentials, environment-specific
configuration, or unrelated runtime data.

## Pull Request or Review Handoff

Include:

- a concise outcome-first summary;
- the reason for the change and approved scope;
- files and architecture boundaries affected;
- compatibility and security considerations;
- focused and full test commands with exact results;
- documentation and static checks performed;
- known limitations, follow-up work, and explicit non-goals;
- confirmation that no unrelated files or runtime artifacts are included.

Reviewers should reject changes that duplicate an existing pathway, introduce
hidden global dependencies, cross package ownership without justification,
weaken trust boundaries, or claim unimplemented behavior.

### Code review checklist

- [ ] The diff matches the approved objective and excludes unrelated changes.
- [ ] The module owner and dependency direction are correct.
- [ ] Existing contracts and extension points are reused.
- [ ] Public APIs, aliases, commands, events, and configuration remain compatible.
- [ ] Inputs, provider results, state transitions, and failure paths are validated.
- [ ] Execution authority and security boundaries are unchanged or explicitly approved.
- [ ] Tests cover success, failure, validation, and compatibility behavior.
- [ ] Documentation matches implemented behavior and labels future work clearly.
- [ ] Logs, events, fixtures, and examples contain no secrets or sensitive data.
- [ ] Quality-gate evidence and exact commands are included.

### Sprint completion checklist

- [ ] Objective and non-goals are satisfied.
- [ ] Focused and full tests pass.
- [ ] `git diff --check` passes.
- [ ] Only approved files are modified.
- [ ] No test was removed or weakened to accept the change.
- [ ] Documentation, changelog, state, roadmap, and recovery records are current as applicable.
- [ ] Runtime artifacts and secrets are absent from the diff.
- [ ] Compatibility, risk, limitations, and follow-up work are reported.
- [ ] Commit, push, merge, and tag remain separate approved actions.

## Release Workflow

Releases require synchronized code, tests, documentation, and Git history:

1. Complete architecture and compatibility review.
2. Pass focused tests, the full suite, and `git diff --check`.
3. Synchronize changelog, README, architecture, state, roadmap, and recovery
   documentation.
4. Obtain commit approval, commit, and verify the commit.
5. Obtain push approval and push the branch.
6. Obtain tag approval, create an annotated tag, verify its target, and push it.
7. Confirm the final branch, commit, tag, remote, and working-tree state.

### Release readiness checklist

- [ ] Architecture and code reviews are complete.
- [ ] Accepted test baseline passes on the release candidate.
- [ ] Version, phase, milestone, changelog, state, roadmap, and recovery claims agree.
- [ ] Public setup, supported environments, limitations, and non-goals are accurate.
- [ ] Compatibility and any approved migration path are documented.
- [ ] Security, rollback, recovery, and operational risks are reviewed.
- [ ] Commit, branch, remote, and annotated tag target are verified.
- [ ] Release notes contain only implemented and validated claims.

## Version and Branch Expectations

Version identifiers describe completed scope, not intent. Phase/sprint tags use
the established `v<version>-phase<phase>-sprint<sprint>` convention, and
published tags are immutable. Breaking public changes require an explicitly
approved major-version and migration plan.

The repository currently contains `main`, `develop`, and `develop-v1.1`;
Version 1.4 work is currently performed on `develop-v1.1`. Contributors must
not infer merge, promotion, branch creation, or release authority from those
names. Use only the branch and Git operations approved for the task.

## Contributor FAQ

### Where does a new provider belong?

Implement the existing domain provider contract and register it at the approved
composition boundary. Do not make domain services construct concrete providers.

### Can I refactor a completed module while adding a feature?

Only if the refactor is explicitly approved and required by the feature.
Otherwise preserve completed modules and keep the change focused.

### Can an Agent plan or orchestration plan call the operating system?

No. Planning records do not carry execution authority. Host-capable work must
follow typed trusted-execution boundaries and use explicitly injected adapters.

### What if the full suite creates local warnings?

Optional audio, camera, OCR, or device warnings may be expected. Failures are
not. Report warnings that materially affect the requested capability.

### What if documentation conflicts with code?

Use the truth order in `Docs/AI_DEVELOPMENT_RULES.md`: Git and current files,
source/tests, explicit instructions, documentation, then prior chat history.
Report and correct documentation drift within approved scope.

### May I commit or push after tests pass?

Not automatically. Implementation, commit, push, and tagging are separate
approval checkpoints.

## Recovery

For interrupted work, a new machine, or a fresh AI session, follow
[Docs/CODEX_RECOVERY_PROMPT.md](Docs/CODEX_RECOVERY_PROMPT.md) and
[Docs/RECOVERY_CHECKLIST.md](Docs/RECOVERY_CHECKLIST.md). Do not reset, restore,
or delete uncommitted work without explicit authorization.
