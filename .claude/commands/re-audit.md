---
description: Re-audit changes from /execute; max 3 loops before escalation
---

Same rigor as `/build-audit`, but scope is the **diff since the last `/execute`** (not the full phase diff).

## Loop counter

Read `plan/phase_<N>_loop.txt`. This is iteration M.

## Execute audit

1. `git diff HEAD` to get the uncommitted diff (which is the execute output since `/wrap` hasn't run yet)
2. Read every file in the diff
3. Audit using `audit-prompt.md` checks, same severity rubric
4. Second-opinion tool pass (same fallback chain as `/build-audit`)

## Exit logic

**If zero findings (or only `low` severity):**
- Delete `plan/phase_<N>_loop.txt`
- End with: `> Re-audit clean. Next: /test`

**If findings AND M < 3:**
- Append findings to `plan/phase_<N>_audit_fix.md` (new section: "Re-audit Loop M")
- Increment `plan/phase_<N>_loop.txt` to M+1
- End with: `> Re-audit found <N> new findings. Loop <M+1> of max 3. Next: /clear then /execute.`

**If findings AND M == 3:**
- Do NOT continue looping
- Write `plan/phase_<N>_escalation.md` with:
  - Summary of remaining unresolved issues
  - Why automation cannot resolve them
  - Three options for the user: (a) accept as-is, (b) deeper refactor, (c) defer to a follow-up phase
- End with the standard escalation block (see `SKILL.md` → "When to escalate to the user"):

> **ESCALATION: Phase <N> hit max re-fix loops (3) with <N> unresolved issues.**
> Context: <2-3 lines summarizing the categories of remaining findings>
> See `plan/phase_<N>_escalation.md` for full detail.
> Options:
>   (a) accept as-is
>   (b) deeper refactor
>   (c) defer to a follow-up phase
> Awaiting user decision.
