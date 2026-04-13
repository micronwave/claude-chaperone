# Phase <N> Handoff

> Written at end of Phase <N> by `/wrap`. Read at start of Phase <N+1> by `/build`.

## Phase completed

<one-line summary of what Phase N accomplished>

## Commit reference

Local commit: `<short SHA>` — `<commit message first line>`

## Files changed

- `path/to/file_1.py` — <what changed>
- `path/to/file_2.py` — <what changed>

## Tests added

- `test_<name>` in `<file>` — <what it verifies>

## Exports / interfaces created

Things downstream phases can rely on:

- `<module>.<function>(<args>) -> <return>` — <description>
- `<class>.<method>` — <description>
- Schema changes: <columns added / tables created>

## Known deferred items

Things we intentionally didn't do, that Phase N+1 or later should handle:

- <deferred item 1>
- <deferred item 2>

## Gotchas for the next phase

- <non-obvious thing Phase N+1 should know>
- <workaround or invariant Phase N established>

## Next phase entry pointer

**Start Phase N+1 by reading:**
1. This file
2. `plan/phase_<N+1>.md`
3. `CLAUDE.md`

Then run `/build`.
