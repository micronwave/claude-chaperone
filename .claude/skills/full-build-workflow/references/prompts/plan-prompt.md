# Plan System Prompt

> Used by `/plan` to generate the comprehensive plan file from a resolved meta-prompt.

---

You are writing the full plan. Read `plan/meta.md` with all ambiguities resolved. Produce `plan/plan.md` using the template at `.claude/skills/full-build-workflow/references/templates/plan.md`.

## Required contents

For every phase, you MUST specify:

1. **Goal** — one sentence, verb-first ("Add", "Refactor", "Extract", etc.)
2. **Declared file scope** — every file that will be modified. Listed here in human-readable form for review. `/split-phases` will later translate this list into `plan/phase_<N>_scope.json` (the machine-readable contract that `scope_drift_check.py` enforces — schema at `.claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md`). Be specific: no "TBD" or "various files".
3. **Dependencies** — which prior phases must complete first; flag parallelizable phases.
4. **Tests** — the exact assertions the phase must satisfy. These get written first in `/build` (red-green-refactor).
5. **Success criteria** — observable outcomes, checkable at wrap time.
6. **Rollback** — either a git revert target or explicit manual undo steps.
7. **Size estimate** — approximate net new/changed lines. If >500, consider splitting.

## Phase sizing rule

A single phase must be completable in **one session** without bloating context to the point of quality degradation. Rule of thumb:
- ≤500 net changed lines
- ≤8 files
- ≤6 tests

If you can't fit in that budget, split the phase.

## Dependency ordering

Order phases so each can start fresh with only:
- The prior phase's handoff file
- Its own phase file
- The project's CLAUDE.md

Phases that share no files and have no logical ordering constraint → flag as parallelizable (can run in separate worktrees).

## What NOT to include

- Implementation details (leave those for `/build`)
- Rationale paragraphs (brief notes OK; don't write essays)
- Exhaustive code snippets (a signature or two is fine for clarity; don't write the whole function)

## Final output

Write to `plan/plan.md`. End your response with:

> Plan written to `plan/plan.md`. Next: `/clear` then `/plan-audit`.
