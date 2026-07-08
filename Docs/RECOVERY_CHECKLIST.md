# Recovery Checklist

## New Codex Chat Recovery
- Confirm current branch with `git branch --show-current`.
- Confirm current HEAD with `git rev-parse HEAD`.
- Inspect `git status --short --untracked-files=all` before doing anything else.
- Read:
  - `Docs/NARVIS_PROJECT_STATE.md`
  - `Docs/NARVIS_DEVELOPMENT_ROADMAP.md`
  - `Docs/NARVIS_DECISIONS.md`
  - `Docs/CODEX_RECOVERY_PROMPT.md`
  - `README.md`
- Verify the documents against:
  - `narvis.py`
  - `Evolution/runtime.py`
  - `Internet/runtime.py`
  - `Skills/builtin.py`
  - relevant tests
- Identify the last completed phase from Git history, not chat history.
- Make no code changes until repository state is understood.

## New Computer Recovery
- Clone the repository.
- Confirm the expected branch and HEAD.
- Read the recovery docs before running the application.
- Run the baseline test suite: `python -m unittest`.
- Confirm no local machine-specific artifacts were committed.
- Verify optional runtime dependencies separately from repository truth.

## Repository Clone Recovery
- Inspect recent commits with `git log --oneline -12`.
- Compare the current checkout to `Docs/NARVIS_PROJECT_STATE.md`.
- Verify that the composition root is still `narvis.py`.
- Verify that Evolution remains in `observe_only` unless code proves otherwise.

## Interrupted Development Recovery
- Check `git status --short --untracked-files=all`.
- Review `git diff --stat` and `git diff` before any restore/reset.
- Separate intended source changes from runtime artifacts.
- Re-run tests before resuming implementation.

## Branch / HEAD / Status Checks
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short --untracked-files=all`
- `git log --oneline -12`

## Before Any Reset Or Checkout
- Confirm whether there is uncommitted work.
- Review the diff.
- Do not discard changes you did not make.
- Ask for confirmation before destructive cleanup.

## Test Baseline
- Run `python -m unittest`.
- Run `git diff --check`.
- Prefer focused suites first if debugging a specific subsystem.

## Runtime Artifact Hygiene
- Confirm `data/memory.sqlite3` is not accidentally modified or staged.
- Confirm tracked pycache artifacts such as `AI/__pycache__/brain.cpython-313.pyc` are clean before commit.
- Check for temporary runtime directories under `data/` created by manual verification.

## Identify The Last Completed Phase
- Use Git history and test coverage, not memory or chat assumptions.
- Confirm the highest completed Self-Evolution phase from recent commits.
- Confirm earlier Internet/Desktop phases from commit history and live code wiring.

## Resume Only After Understanding State
- Verify recovery docs against actual code.
- Verify current capabilities against runtime wiring and tests.
- Confirm the next phase before implementation.
- Avoid starting a later phase just because it appears in the roadmap.
