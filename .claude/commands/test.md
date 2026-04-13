---
description: Run the project test suite; on failure loop back to /execute or escalate
---

Run the project's test command. Read `CLAUDE.md` or convention for the exact command — common patterns:

- Python: `python -X utf8 tests/test_<phase>.py` or `pytest tests/`
- Node: `npm test` or `npx jest`
- Go: `go test ./...`

Capture output.

## Outcomes

**All green:**
- Append to `BUILD_LOG.md`: "Phase <N> tests green, <N> passed"
- End with: `> All tests passing. Next: /wrap`

**Failure in new code (new tests added in this phase are red):**
- Analyze the failure
- If it's a fixable bug in phase code, end with:

> Test failures in Phase <N> new code: <N> failing.
> <brief summary of failures>
> Next: `/clear` then `/execute` (add a fix for each failure to `plan/phase_<N>_audit_fix.md` first).

**Regression (previously-green tests now failing):**
- ESCALATE — this is a serious signal
- End with:

> **ESCALATION: regression detected. Tests that were green before Phase <N> are now red:**
> - <test name> — <error>
> Awaiting user decision: (a) treat as Phase <N> bug and fix, (b) revert Phase <N>, (c) accept regression (rare, requires justification).
