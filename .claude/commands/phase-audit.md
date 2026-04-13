---
description: Audit each per-phase file for self-containedness and readiness
---

Audit every `plan/phase_<N>.md` file. Scope: all phase files. Comprehensive.

## Per-phase checks

- **Self-containedness** — could a fresh session execute this knowing only this file + prior handoff + CLAUDE.md?
- **Dependencies satisfied** — will the prior phases have produced what this phase needs?
- **Tests defined** — are the tests concrete (actual assertions, not descriptions)?
- **Declared file scope is specific** — no "TBD" or "various files" in the phase markdown's scope list
- **Scope contract exists and validates** — `plan/phase_<N>_scope.json` is present, parses as JSON, conforms to the schema at `.claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md`, its `phase_number` matches N, and every `prefixes` entry ends with `/`. This JSON — not the markdown — is what `scope_drift_check.py` reads.
- **Scope markdown and scope JSON agree** — the human-readable file list in `phase_<N>.md` matches `scope.files` + `scope.prefixes` in the JSON. Divergence is a bug.
- **Rollback is real** — the commit target or undo steps exist and would work
- **Size is within budget** — ≤500 lines, ≤8 files, ≤6 tests

## Patch in place

If a phase file has gaps, patch the file directly (not a separate audit_fix at this stage — phase files are still plans, not code). Keep changes surgical.

## Second-opinion tool (optional)

Same fallback chain as `/plan-audit` — external tool if available, subagent otherwise.

End with:

> Phase audit complete. <N> phase files reviewed. <N> patched. Next: `/clear` then `/build` to start Phase 1.
