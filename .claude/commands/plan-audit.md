---
description: Comprehensive audit of the full plan file
---

Audit `plan/plan.md` in full. Scope: the entire plan. Comprehensive — no sampling.

## Checks

- **Feasibility** — does every phase fit in one session (≤500 lines, ≤8 files, ≤6 tests)?
- **Dependency correctness** — will phase N have everything it needs from phase N-1's declared outputs?
- **Missing phases** — anything assumed but not planned?
- **Bad abstractions** — over- or under-engineering relative to the meta-prompt intent?
- **Testability** — can every phase be verified with its listed tests?
- **Scope creep** — anything outside the resolved meta-prompt's scope boundary?
- **Rollback viability** — is every rollback target real and sufficient?

## Second-opinion tool (optional)

Check if `codex`, `gemini`, or `aider` is available on `PATH`. If yes and `CBW_DISABLE_SECOND_OPINION` is not set:
- Send the plan (or its diff vs prior version if re-auditing) to the first available tool
- Merge findings with your own (see `docs/SECOND_OPINION.md`)

If no external tool, spawn a subagent (`Agent`, `subagent_type: general-purpose`) to do an independent pass in isolated context.

## Output

Write `plan/plan_audit.md` with findings. If fixes are warranted, also update `plan/plan.md` in place.

End with:

> Plan audit complete. Findings: <N> critical, <N> high, <N> medium, <N> low. **User action: review `plan/plan.md` and approve or request changes.** When approved: `/clear` then `/split-phases`.
