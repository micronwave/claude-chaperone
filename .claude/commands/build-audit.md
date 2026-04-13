---
description: Comprehensive diff-scoped audit producing audit_fix.md
---

Load the audit system prompt from `.claude/skills/full-build-workflow/references/prompts/audit-prompt.md`.

## Scope

The uncommitted diff of the current phase. Run `git diff --name-only` to get the file list. Every file in that list, read in full, audited comprehensively. No sampling.

## Execution

1. Read the phase file `plan/phase_<N>.md` for context on what was supposed to happen
2. Read every file in `git diff --name-only` (post-phase-build state)
3. Audit using the checks in `audit-prompt.md`: correctness, security, performance, test coverage, style
4. **Second-opinion pass** — check for `codex`, `gemini`, or `aider` on PATH. If available and `CBW_DISABLE_SECOND_OPINION` is not set, run it on the diff. Merge findings (prefix `EXTERNAL_ONLY:`, `CLAUDE_ONLY:`, `BOTH:`, `CONFLICT:` per SECOND_OPINION.md).
5. Fall back to subagent audit (`Agent` with `subagent_type: general-purpose`) if no external tool is available.

## Output

Write `plan/phase_<N>_audit_fix.md` using the template at `.claude/skills/full-build-workflow/references/templates/audit_fix.md`.

Each finding must include: severity, category, source, file+line, issue, fix, rationale (if non-obvious).

## Set re-fix loop counter

Write `plan/phase_<N>_loop.txt` containing `1` (this is iteration 1 of max 3).

End with:

> Build audit complete. <N> findings (<N> critical, <N> high, <N> medium, <N> low). <N> conflicts requiring user input.
> Next: `/clear` then `/execute` (or resolve conflicts first if any).
