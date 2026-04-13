---
description: Generate comprehensive plan file from meta-prompt
---

Load the plan system prompt from `.claude/skills/full-build-workflow/references/prompts/plan-prompt.md` and the plan template from `.claude/skills/full-build-workflow/references/templates/plan.md`.

Read `plan/meta.md` (with resolved ambiguities) and produce `plan/plan.md`.

Requirements recap (enforce strictly):
- Every phase has: goal, declared file scope, dependencies, tests, success criteria, rollback, size estimate
- Phase sizing ≤500 net changed lines, ≤8 files, ≤6 tests — split if larger
- Order phases so each can start fresh from only the prior handoff + its phase file + CLAUDE.md
- Flag parallelizable phases

End your response with:

> Plan written to `plan/plan.md`. Next: `/clear` then `/plan-audit`.
