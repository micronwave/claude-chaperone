# Phase Scope JSON — Schema Contract

> Source of truth for the scope-drift hook. Changing this format without also updating `.claude/hooks/scope_drift_check.py` will break enforcement silently. Don't do that.

## File location

`plan/phase_<N>_scope.json` — one per phase, written by `/split-phases`, amended only when a scope-drift decision is "accept drift".

## Required fields

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | integer | Currently `1`. Bump + migrate if format changes. |
| `phase_number` | integer | Must match the `N` in the filename and in `plan/current_phase.txt` |
| `phase_name` | string | Human-readable label |
| `scope.files` | array of strings | Exact paths (relative to project root, forward slashes) that may be modified |
| `scope.prefixes` | array of strings | Directory prefixes (trailing slash required) under which any file may be modified |
| `scope.allow_untracked_new` | boolean | If `true`, new files created under a `prefixes` entry are allowed even without being listed in `files` |

## Optional fields

| Field | Type | Purpose |
|---|---|---|
| `notes` | string | Free text for humans; ignored by hooks |

## Universal allowlist (hardcoded in the hook — not in scope.json)

These paths are ALWAYS allowed and do not count as drift:

- `BUILD_LOG.md`
- `plan/current_phase.txt`
- `plan/phase_<N>_audit_fix.md`
- `plan/phase_<N>_handoff.md`
- `plan/phase_<N>_loop.txt`
- `plan/phase_<N>_escalation.md`
- `plan/phase_<N>_scope.json` (this file itself — editable when accepting drift)

## Path matching rules

1. Git always returns forward-slash paths, even on Windows. The scope file must use forward slashes.
2. Comparison is case-sensitive (matches git's default).
3. A changed file matches the scope if any of:
   - It equals an entry in `scope.files` exactly, OR
   - Its path starts with any entry in `scope.prefixes` (which must end in `/`), OR
   - It's in the universal allowlist.
4. Renames in git appear as a deletion + addition. Both must be in scope or both flagged as drift.
5. Deletions of in-scope files are considered in-scope modifications.

## Example

```json
{
  "$schema_comment": "...",
  "schema_version": 1,
  "phase_number": 3,
  "phase_name": "async job queue",
  "scope": {
    "files": [
      "workers/queue.py",
      "workers/__init__.py",
      "tests/test_queue.py"
    ],
    "prefixes": [
      "docs/architecture/"
    ],
    "allow_untracked_new": true
  },
  "notes": "Phase 3 adds the Redis-backed job queue. The docs/architecture prefix allows new ADR files without listing each by name."
}
```

## Failure modes (LOUD, not silent)

The hook emits a structured error to stderr and exits 0 (non-blocking) in these cases, so the user sees the problem immediately:

- `plan/current_phase.txt` exists but scope JSON is missing → `MISSING_SCOPE_FILE`
- JSON is malformed → `MALFORMED_SCOPE_JSON: <details>`
- Required field missing → `INVALID_SCOPE_SCHEMA: missing <field>`
- `phase_number` in JSON ≠ pointer in `current_phase.txt` → `SCOPE_PHASE_MISMATCH`
- `prefixes` entry doesn't end in `/` → `INVALID_PREFIX: <entry>`

None of these are silent. The hook will NOT pass a file through as "in scope" if it can't load the scope file — it will report the config error.
