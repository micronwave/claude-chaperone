---
description: Execute a phase with strict test-first discipline
---

Load the build system prompt from `.claude/skills/full-build-workflow/references/prompts/build-prompt.md`.

Read:
1. `plan/current_phase.txt` → determines N
2. `plan/phase_<N>.md` (human-readable spec)
3. `plan/phase_<N>_scope.json` (machine-readable scope contract — the source of truth for allowed files)
4. `plan/phase_<N-1>_handoff.md` (if N > 1)
5. `CLAUDE.md`

Execute the phase using strict red-green-refactor. Append to `BUILD_LOG.md` at each transition (tests written, implementation green, refactor done).

## Scope discipline (non-negotiable)

The ONLY files you may modify are:
- Entries in `scope.files` from `plan/phase_<N>_scope.json`
- Files under any directory listed in `scope.prefixes`
- Workflow metadata (BUILD_LOG.md, plan/phase_<N>_*.md, plan/phase_<N>_scope.json itself)

If you find yourself needing to edit a file outside scope, STOP. Do not silently expand. Surface the drift to the user with three options:
- (a) Accept — amend `plan/phase_<N>_scope.json` to include the file (this is a deliberate scope change, logged in BUILD_LOG)
- (b) Revert — undo the edit and find another way
- (c) Defer — note it for a later phase in the handoff

The `scope_drift_check.py` hook will automatically surface drift at end of turn as a safety net, but don't rely on it — catch the drift at decision time.

## Do not commit

`/wrap` commits. Premature commits pollute the diff that `/build-audit` needs to read.

## End of turn

> Phase <N> build complete.
> Tests: <passed>/<total>
> Files touched: <count> (all in scope: yes/no)
> Scope drift: <none | list>
> Next: `/clear` then `/build-audit`
