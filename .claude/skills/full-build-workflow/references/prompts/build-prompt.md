# Build System Prompt

> Used by `/build` to execute a single phase from its phase file.

---

You are building Phase `<N>`. Read:

1. `plan/phase_<N>.md` — the human-readable phase spec
2. `plan/phase_<N>_scope.json` — the machine-readable scope contract (source of truth for allowed files)
3. `plan/phase_<N-1>_handoff.md` — the prior handoff (skip if N=1)
4. `CLAUDE.md` — project conventions

Then execute the phase with strict test-first discipline.

## Build sequence

### 1. Red — write failing tests

Implement every test from the phase's "Tests" section. They should all fail (because there's no implementation yet).

Run tests, confirm red:

```
<test runner command>
```

Append to `BUILD_LOG.md`:

```
## <timestamp> — Phase <N> — tests written (red)
Files: <test files>
<N> tests, all failing as expected.
```

### 2. Green — implement

Write the minimum code to make every test pass. Do not add features beyond what the phase specifies.

**Scope discipline (enforced by hook):** only edit files in the phase's `scope.files` or under its `scope.prefixes` (from `plan/phase_<N>_scope.json`). If you find yourself needing to edit a file outside that scope, **stop** and surface the drift — do not silently expand. The `scope_drift_check.py` hook will also surface drift at end of turn as a safety net, but catch it at decision time.

Run tests, confirm green:

```
<test runner command>
```

Append to `BUILD_LOG.md`:

```
## <timestamp> — Phase <N> — implementation green
Files: <implementation files>
<N> tests passing.
Notes: <any non-obvious decision>
```

### 3. Refactor — cleanup only

ONLY if the code is obviously bad (dead code, duplication, unclear names). Not a judgment call about architecture — that's plan-level. Keep tests green throughout.

**Do NOT refactor for:**

- **Performance.** Belongs in a follow-up phase backed by measurements.
- **Architecture or design.** Those decisions were made at `/plan` time. Revisiting them here sidesteps the plan audit gate.
- **"Niceness"** that doesn't match a concrete rule in `CLAUDE.md`.

If you find yourself tempted to restructure, that's a signal the work belongs in a future phase. Note it in the handoff's "Deferred items" section and move on.

## Output at end of turn

Finish with a status block:

```
Phase <N> build complete.
Tests: <passed>/<total>
Files touched: <count>
Scope drift: <none | list>
Next: /clear then /build-audit
```

## Rules

- **Never skip the red step.** Writing tests after implementation is indistinguishable from confirmation bias.
- **Append to BUILD_LOG as you go**, not at the end. If the session crashes, the log is the only state that survives.
- **Do not edit files outside scope.** If needed, stop and surface three options to the user: (a) accept drift — amend `plan/phase_<N>_scope.json` to include the path (logged in BUILD_LOG), (b) revert the edit and find another way, (c) defer to a later phase by noting it in the handoff.
- **Do not commit.** `/wrap` commits. Premature commits during build pollute the diff the audit needs to read.
