# Session Bootstrap

> Small always-loadable file. Points the current session at the right phase and handoff. Read this at the start of any fresh session to avoid re-deriving project state.

## Current phase

**Phase number:** `<N>`
**Phase file:** `plan/phase_<N>.md`
**Scope contract:** `plan/phase_<N>_scope.json` (machine-readable, read by `scope_drift_check.py`)
**Prior handoff:** `plan/phase_<N-1>_handoff.md` (or "none" if N=1)

## Session entry point

Depending on where you are in the phase loop:

| You are about to run | Prerequisites |
|---|---|
| `/build` | Read `plan/phase_<N>.md` + prior handoff |
| `/build-audit` | Read `plan/phase_<N>.md` + git diff of uncommitted changes |
| `/execute` | Read `plan/phase_<N>_audit_fix.md` |
| `/re-audit` | Read `plan/phase_<N>_audit_fix.md` + git diff since last execute |
| `/test` | Read `plan/phase_<N>.md` for success criteria |
| `/wrap` | Read everything above to synthesize handoff |

## Invariants for this project

- <insert project-specific invariants here — e.g., "Always use repository pattern for DB access">
- <e.g., "All async functions use anyio, not asyncio directly">
- <e.g., "Tests run via `python -X utf8 tests/test_*.py`, no pytest">

## Do not re-derive

The following are **already decided**; do not re-litigate:

- <e.g., "Auth is JWT, not sessions">
- <e.g., "SQLite for persistence, not Postgres, until 100k narratives">
- <e.g., "Frontend is Next.js App Router, not Pages Router">
