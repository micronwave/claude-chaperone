---
description: Split the approved plan into per-phase files sized for single sessions
---

Read `plan/plan.md` (user-approved). For each phase, produce TWO artifacts:

## 1. Human-readable phase file

Write `plan/phase_<N>.md` as a self-contained phase spec. Self-contained means a fresh session can execute the phase knowing only:
1. This phase file
2. The prior phase's `plan/phase_<N-1>_handoff.md` (if N>1)
3. The project's `CLAUDE.md`
4. This phase's `plan/phase_<N>_scope.json` (the machine-readable contract)

The phase file should include: goal, dependencies, tests (as concrete assertions), success criteria, rollback, size estimate, and a reference to the scope JSON file.

## 2. Machine-readable scope contract

Construct the scope JSON in memory first and self-validate BEFORE writing to disk. For each phase, confirm:

1. It parses as JSON (no trailing commas, no unquoted keys)
2. `phase_number` equals the N you're writing
3. Every entry in `scope.prefixes` ends with `/`
4. `schema_version` is `1`
5. All paths use forward slashes

If any check fails, regenerate — don't write a file you know the hook will reject. Catching it here avoids a surprise when `/build` fires the hook.

Write `plan/phase_<N>_scope.json` following the schema at `.claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md`. Required fields:

```json
{
  "schema_version": 1,
  "phase_number": <N>,
  "phase_name": "<short label>",
  "scope": {
    "files": ["<exact paths, forward slashes>"],
    "prefixes": ["<dir prefixes ending in />"],
    "allow_untracked_new": <bool>
  },
  "notes": "<optional human notes>"
}
```

**Critical requirements — the scope-drift hook will LOUDLY fail if these are violated:**

- Every prefix entry MUST end in `/`
- Paths use forward slashes on all platforms
- `phase_number` in the JSON MUST match the filename
- `schema_version` MUST be `1`

The hook validates these at runtime; don't rely on manual review.

## 3. Advance the phase pointer

Write `plan/current_phase.txt` containing just the number `1` (no trailing newline is fine). This is the pointer the scope-drift and stop-reminder hooks read to decide whether the workflow is active.

## Final output

End with:

> Split into <N> phase files and <N> scope contracts (the JSON files read by the scope-drift hook).
> Phase files: `plan/phase_1.md` ... `plan/phase_N.md`
> Scope JSONs: `plan/phase_1_scope.json` ... `plan/phase_N_scope.json`
> Pointer: `plan/current_phase.txt` = 1
> Next: `/clear` then `/phase-audit`
