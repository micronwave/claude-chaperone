---
name: full-build-workflow
description: Universal multi-phase build workflow for Claude Code. Auto-triggers when the user mentions building a new feature, starting a phase, auditing code, handing off work, or wrapping up a session. Orchestrates the full sequence from rough idea to committed code with comprehensive audits and deterministic handoffs.
---

# Full Build Workflow

A disciplined, phase-gated workflow for building production-grade software with Claude Code. Optimized for **code quality** (bug-free) and **context efficiency** (minimal rot).

## When this skill applies

Trigger this skill whenever the user says anything like:
- "I want to build X / add X / implement X"
- "Let's start a new feature"
- "Start phase N" / "continue with phase N"
- "Audit this" / "audit the plan" / "audit the build"
- "Write a handoff" / "hand this off"
- "Wrap up this phase" / "commit and wrap"

Do **not** trigger for small one-off tweaks (fixing a typo, renaming a variable, reading a file). Those don't need the full workflow.

## Core principles (never violate)

1. **Every phase fits one session.** If a phase is too big to finish without your context bloating, split it.
2. **`/clear` between stages.** After every audit, build, execute, re-audit. Never skip.
3. **Handoff files carry state, not chat memory.** A new session must be able to pick up from the handoff file alone.
4. **Audits are scope-bounded but comprehensive.** Diff-scoped for build/re-audit; phase-scoped for phase audit; plan-scoped for plan audit. Within the scope, every file, every function, every test.
5. **Max 3 re-fix loops.** On the 3rd unresolved re-audit, escalate to user.
6. **User owns architecture, you own mechanical work.** Explicit approval gates at architectural forks.
7. **Never `git push`.** Local commits only. User pushes when satisfied.

## The sequence

| # | Command | Actor | Clears after? | Notes |
|---|---|---|---|---|
| 1 | `/meta-prompt` | Claude | Yes | Produces `plan/meta.md` + ambiguity register |
| — | (ambiguity gate) | User | — | User resolves ambiguities before proceeding |
| 2 | `/plan` | Claude | Yes | Produces `plan/plan.md` |
| 3 | `/plan-audit` | Claude | Yes | Comprehensive plan audit; optionally calls second-opinion tool |
| — | (architecture gate) | User | — | User approves the plan |
| 4 | `/split-phases` | Claude | Yes | Produces `plan/phase_1.md` … `plan/phase_N.md` |
| 5 | `/phase-audit` | Claude | Yes | Per-phase audit; patches phase files |
| — | **(per phase, repeat)** | — | — | — |
| 6 | `/build` | Claude | Yes | Tests first; appends to BUILD_LOG during |
| 7 | `/build-audit` | Claude | Yes | Diff-scoped comprehensive audit → `audit_fix.md` |
| 8 | `/execute` | Claude | Yes | Applies audit_fix items |
| 9 | `/re-audit` | Claude | Yes | Max 3 loops; on 3rd, escalate |
| 10 | `/test` | Claude | No | Run suite; on red go back to `/execute` |
| 11 | `/wrap` | Claude | Yes | BUILD_LOG final + local commit + handoff |

## Outputs you will produce

- `plan/meta.md` — meta-prompt output
- `plan/plan.md` — full plan
- `plan/plan_audit.md` — plan audit findings
- `plan/phase_N.md` — per-phase human-readable spec (N = 1..N)
- `plan/phase_N_scope.json` — per-phase machine-readable scope contract (read by `scope_drift_check.py` — see `references/templates/SCOPE_SCHEMA.md`)
- `plan/phase_N_audit_fix.md` — per-phase audit_fix files
- `plan/phase_N_handoff.md` — per-phase handoff files
- `plan/phase_N_loop.txt` — re-audit loop counter (1..3). Written by `/build-audit`, incremented by `/re-audit`, deleted when the re-audit comes back clean.
- `plan/phase_N_escalation.md` — written by `/re-audit` ONLY when the 3-loop limit is hit with unresolved findings. Absent on a clean run.
- `BUILD_LOG.md` — running log, appended throughout
- `plan/current_phase.txt` — single-line pointer to the current phase number (read by all hooks to decide whether the workflow is active)

**Critical:** `phase_N_scope.json` is the SOURCE OF TRUTH for scope-drift enforcement. Its schema is strict — the hook LOUDLY fails on missing/malformed/invalid files rather than silently passing everything as in-scope. See `references/templates/SCOPE_SCHEMA.md`.

## Second-opinion tool integration

When running `/build-audit` or `/re-audit`:

1. Check if `codex`, `gemini`, or `aider` is on `PATH` (probe via a no-op `--version` call).
2. If yes and `CBW_DISABLE_SECOND_OPINION` is not set: run that tool on the diff with `references/prompts/audit-prompt.md`.
3. Merge its findings into `audit_fix.md` alongside your own.
4. If it finds something you didn't, flag `EXTERNAL_ONLY:` on that item.
5. If you find something it didn't, flag `CLAUDE_ONLY:` on that item.
6. If both agree, no prefix (high-confidence finding).
7. If you disagree, flag `CONFLICT:` and surface to user.

If no external tool is available: run the audit inside a subagent (`Agent` tool, `subagent_type: general-purpose`) instead of in the main session. This provides isolated context even without a different model.

## Handling `/clear` (the coordination challenge)

You cannot invoke `/clear` yourself. Every command's final output line must be the **exact next command** the user should run, phrased as a single pasteable string:

> `Next: /clear then /build-audit`

Users paste that directly. One keystroke per gate.

For audit steps that would benefit from a fresh context but don't require a full session clear, prefer spawning a subagent — it gets the isolation benefits without requiring user action.

## Scope-drift discipline

The `scope_drift_check.py` hook fires after every file edit. It reads `plan/phase_<N>_scope.json` (the machine-readable contract) — NOT the markdown phase file. If it reports drift:

1. Do not continue editing.
2. Surface the drift list to the user at end of turn.
3. Offer three options: (a) accept drift — amend `plan/phase_N_scope.json` to include these paths (logged in BUILD_LOG); (b) revert the out-of-scope edits; (c) amend and continue with explicit justification.
4. Wait for user decision before proceeding.

If the hook emits `SCOPE_DRIFT_HOOK_ERROR`, the scope JSON itself is broken — fix it (schema violation, missing file, malformed JSON) before continuing. The hook is currently NOT protecting you in that state.

## When to escalate to the user

- After 3 unresolved re-audit loops (remaining issues are judgment calls)
- When an audit surfaces `SCOPE_RECONSIDER_NEEDED` (the change violates meta-prompt intent)
- When scope drift is detected
- When a test failure is in previously-green code (regression)
- When a `CONFLICT:` finding appears between Claude and a second-opinion tool

Escalation format:

```
ESCALATION: <one-line summary>
Context: <2-3 lines>
Options:
  (a) <option 1>
  (b) <option 2>
  (c) <option 3>
Awaiting user decision.
```

## Reference files

- Templates: `references/templates/` — plan, handoff, audit_fix, build_log, bootstrap
- Prompts: `references/prompts/` — meta, plan, build, audit

Read the specific template or prompt you need; do not load all of them.
