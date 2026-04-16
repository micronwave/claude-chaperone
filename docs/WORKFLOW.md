# Workflow Reference

Full detail on each phase, each gate, and the rationale behind the design.

---

## Phase 0.0 — (optional) `/chaperone`

A router command, not a workflow stage. Two behaviors:

1. With arguments: `/chaperone "rough idea"` → user is told to paste `/meta-prompt "rough idea"`. The workflow proceeds normally from Step 0.1.
2. Without arguments: prints a state snapshot (current phase, last BUILD_LOG header, suggested next command) OR, if no workflow is active, prints a short orientation + offer.

Why separate from `/meta-prompt`? Discoverability. New users don't know what "meta-prompt" means. Returning users don't always remember which of the 12 commands is next. `/chaperone` is one memorable name for both entry and resume.

Does NOT auto-execute anything. The user pastes the suggested command. Preserves the `/clear`-between-stages invariant.

---

## Phase 0 — Intake

### Step 0.1 — Initial prompt (user)

User submits a rough description of what they want built. Example: *"I want a narrative engine that clusters news into trend signals."*

### Step 0.2 — `/meta-prompt` (Claude)

Claude performs **scoped** project research (grep-driven, not a full walk) and rewrites the user prompt into a **detailed requirements spec** that includes:

- Intent statement (plain English)
- Explicit success criteria (how we know "done")
- **Ambiguity register** — every decision Claude *would otherwise have to guess on*
- Suggested scope boundary (what's in / what's out)
- Named files or subsystems expected to be touched (shortlist, not exhaustive)

**Output:** `plan/meta.md`

### Step 0.3 — Ambiguity gate (user)

User reads the ambiguity register and resolves every item. Claude does **not** proceed until every ambiguity has an answer or an approved default.

Reason: the single biggest cause of rework is Claude guessing an architecture decision the user would have answered differently in 30 seconds.

---

## Phase 1 — Plan

### Step 1.1 — `/clear`

### Step 1.2 — `/plan` (Claude)

Claude reads `plan/meta.md` and generates `plan/plan.md` containing:

- **Phases** — each sized to fit a single session (rule of thumb: <500 lines of net new/changed code)
- **Dependencies** — strict ordering, with parallelizable phases flagged
- **Affected files** per phase (declared scope — enforced later by scope-drift hook)
- **Test scaffolding** per phase — what "done" looks like as executable assertions
- **Rollback plan** — how to revert if a phase fails mid-build
- **Success criteria** per phase — the acceptance contract

### Step 1.3 — `/clear`

### Step 1.4 — `/plan-audit` (Claude, comprehensive)

Claude audits the **entire plan** for:

- Feasibility — does every phase fit in one session?
- Dependency correctness — will phase N have what it needs from phase N-1?
- Missing phases — is anything assumed without being planned?
- Bad abstractions — are we over-engineering or under-engineering?
- Testability — can we actually verify each phase?
- Scope creep — did we include anything not in the resolved meta-prompt?

**Optionally invokes second-opinion tool** (see `SECOND_OPINION.md`).

**Output:** `plan/plan_audit.md` — findings + a revised `plan/plan.md` if issues found.

### Step 1.5 — User approval gate (architecture)

User reviews `plan/plan.md`. This is the **single highest-leverage human review point in the entire workflow** — architecture decided wrong here propagates through every phase.

If user requests changes → return to `/plan`. If approved → proceed.

---

## Phase 2 — Phase Preparation

### Step 2.1 — `/clear`

### Step 2.2 — `/split-phases` (Claude)

Claude splits `plan/plan.md` into N individual phase files: `plan/phase_1.md`, `plan/phase_2.md`, etc.

Each phase file is **self-contained** — a session can execute it knowing only:

1. The phase file itself
2. The prior phase's `handoff.md`
3. The project's `CLAUDE.md`

### Step 2.3 — `/clear`

### Step 2.4 — `/phase-audit` (Claude, comprehensive)

Audits each phase file for:

- Self-containedness (does it have everything a fresh session needs?)
- Dependencies satisfied by prior phases
- Tests defined
- Rollback defined
- Scope clearly bounded

**Output:** phase files patched with any gaps filled.

---

## Phase 3 — Per-Phase Build Loop

Executed once per phase, in order.

### Step 3.1 — `/clear`

### Step 3.2 — `/build` (Claude)

Reads:
- The current phase file
- Prior phase's `handoff.md` (if phase > 1)
- `CLAUDE.md`

Executes the phase with **test-first discipline**:

1. Write failing tests from the phase's test scaffolding
2. Implement minimum code to pass tests
3. **Append to `BUILD_LOG.md` as work proceeds**, not only at end — protects against mid-phase crashes

**Scope-drift hook** watches every file edit. If Claude touches a file outside the phase's declared scope, the hook surfaces a warning at end of turn; user decides whether to accept, revert, or amend the phase scope.

### Step 3.3 — `/clear`

### Step 3.4 — `/build-audit` (Claude, comprehensive diff-scoped)

Scope: **every file changed in step 3.2**. Each file is audited **in full** — no sampling.

Checks:
- Correctness against phase success criteria
- Bugs (logic errors, off-by-one, null/empty handling, race conditions, type confusion)
- Security (injection, secrets, auth, path traversal, deserialization)
- Performance red flags (N+1, unbounded loops, hot-path allocations)
- Style / project-convention adherence
- Test coverage of new code paths

**Optionally invokes second-opinion tool** — same diff, independent pass.

**Output:** `plan/phase_N_audit_fix.md` — every finding with a proposed fix.

### Step 3.5 — `/execute` (Claude)

Applies every item in `audit_fix.md`. No judgment — the fixes were decided at audit time.

### Step 3.6 — `/clear`

### Step 3.7 — `/re-audit` (Claude, comprehensive diff-scoped)

Re-audits the files changed by `/execute` using the same rigor as `/build-audit`.

**Exit conditions:**
- Zero issues found → proceed to `/test`
- Issues found AND loop count < 3 → back to `/execute`
- Issues found AND loop count = 3 → **escalate to user** with a summary of remaining issues. User decides: accept as-is, refactor, or defer.

Rationale: infinite polish loops burn budget without improving quality past a point. Three rounds is enough to catch mechanical bugs; beyond that, you're in judgment territory that needs a human.

### Step 3.8 — `/test` (Claude)

Run the project's test suite. If red:
- If failure is in new code → back to `/execute`
- If failure is in previously-green code (regression) → escalate to user

### Step 3.9 — `/wrap` (Claude)

- Append final entry to `BUILD_LOG.md`
- Write `plan/phase_N_handoff.md` for the next phase
- **Local commit only.** Never `git push`. The user pushes when satisfied.

### Step 3.10 — `/clear` → next phase

---

## Rationale for design choices

### Why `/clear` between every stage?

Context rot is the dominant quality killer in long sessions. A fresh session loading only the specific files it needs beats a bloated session every time.

### Why handoff files instead of keeping conversation history?

Conversation memory is non-portable, token-expensive, and opaque. A handoff file is explicit, reviewable, and survives any session boundary.

### Why scope audits instead of "audit everything"?

Auditing the whole project on every build would cost 10-100× more tokens and would find mostly noise (files that weren't touched this round). Diff-scoped audits are **narrower but stricter** — within the scope, nothing is sampled or summarized.

### Why a mandatory re-fix exit condition?

Without one, the workflow can loop indefinitely on cosmetic disagreements between the build pass and the audit pass. Three iterations is the empirical sweet spot — enough to catch real bugs, short enough to prevent budget drain.

### Why optional second-opinion tools?

A self-audit catches maybe 60-70% of bugs a different tool would catch. If users have Codex / Gemini / Aider installed, wiring them in is free value. If they don't, the fallback (same model, isolated subagent) still catches most issues and doesn't require any extra setup.

### Why user approval only at architecture gates?

Users want Claude to be autonomous on mechanical work and collaborative on architectural work. Approval gates at the plan (architecture decided) and on escalation (judgment needed) strike that balance.
