---
description: Finalize phase — BUILD_LOG append, handoff write, local commit (never push)
---

Finalize the current phase.

## Steps

### 1. Final BUILD_LOG entry

Append a wrap entry summarizing the phase:

```
## <timestamp> — Phase <N> — wrapped
**Summary:** <one-line>
**Files changed:** <list>
**Tests:** <count> passing
**Audit iterations:** <M of 3>
**Notes:** <any deferred items or gotchas>
```

### 2. Write handoff

Write `plan/phase_<N>_handoff.md` using the template at `.claude/skills/full-build-workflow/references/templates/handoff.md`. Include:

- One-line summary of what was accomplished
- Files changed + what changed
- Tests added + what they verify
- Exports / interfaces created that downstream phases can use
- Deferred items for later phases
- Gotchas (non-obvious invariants established)

### 3. Local commit

Stage the phase's artifacts explicitly (never `git add -A`):

```
git add <each file from plan/phase_<N>_scope.json scope.files>
git add BUILD_LOG.md
git add plan/phase_<N>_handoff.md
git add plan/phase_<N>_audit_fix.md
git add plan/phase_<N>_scope.json
git commit -m "<phase N>: <one-line goal>"
```

Commit message format: `phase <N>: <verb> <noun>` (e.g., `phase 3: add async queue for batch embeddings`).

**Never `git push`.** The `push_confirm.py` hook emits a permission-ask response when `git push` is detected, so the user will get a prompt. If you attempt a push anyway, it routes through the permission system — not an error, just a gate.

### 4. Advance phase pointer

If there are more phases: write `plan/current_phase.txt` with `<N+1>`.
If this was the last phase: delete `plan/current_phase.txt`.

### 5. End message

If more phases remaining:

> Phase <N> wrapped and committed locally (<short SHA>). Handoff written to `plan/phase_<N>_handoff.md`.
> Next: `/clear` then `/build` to start Phase <N+1>.

If final phase:

> **Build complete.** All <N> phases wrapped. Final commit: <short SHA>.
> Review changes: `git log --oneline HEAD~<N>..`
> When satisfied, push: `git push` (the permission prompt will ask for confirmation).
