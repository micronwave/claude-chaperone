#!/usr/bin/env python3
"""
scope_drift_check.py — PostToolUse hook for Edit / Write / NotebookEdit.

Reads the active phase from plan/current_phase.txt and the scope contract
from plan/phase_<N>_scope.json, then checks whether the edited file is in
scope. Fast path: uses the file_path from the hook payload (no subprocess).
Fallback: runs `git status --porcelain` when no path is in the payload.

Failure modes are LOUD — missing scope file, malformed JSON, or schema
violations produce a visible error instead of silently passing every file as
in-scope. The hook itself is non-blocking (exit 0) so edits still land; the
user decides how to resolve.

Source of truth for the scope format:
    .claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md
"""
from __future__ import annotations

import sys
from pathlib import Path

# Local import — _hook_utils.py is a sibling
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import _hook_utils as hu  # noqa: E402


def main() -> int:
    payload = hu.read_hook_payload()

    phase = hu.read_current_phase()
    if phase is None:
        return 0

    try:
        scope = hu.load_phase_scope(phase)
    except hu.ScopeError as exc:
        hu.emit_stderr_warning(
            f"SCOPE_DRIFT_HOOK_ERROR: {exc}\n"
            f"  The scope-drift guard is not running for phase {phase}. "
            f"Fix the scope file before continuing.\n"
            f"  See .claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md"
        )
        return 0

    # Fast path: payload contains the exact file just edited — no subprocess needed.
    file_path = hu.payload_file_path(payload)
    if file_path is not None:
        if not hu.path_in_scope(file_path, scope, phase):
            hu.emit_stderr_warning(
                f"SCOPE_DRIFT: file changed outside Phase {phase} ({scope.phase_name}) "
                f"declared scope:\n"
                f"  [M] {file_path}\n"
                "Decide: "
                "(a) accept drift — update plan/phase_{n}_scope.json to include this path, "
                "(b) revert the change, "
                "(c) amend and continue with an explicit justification in BUILD_LOG.".format(
                    n=phase
                )
            )
        return 0

    # Fallback path: no file_path in payload (unexpected payload shape).
    # Run git status to catch any accumulated drift.
    try:
        entries = hu.git_changed_paths()
    except hu.GitNotFoundError as exc:
        hu.emit_stderr_warning(
            f"SCOPE_DRIFT_HOOK_ERROR: {exc}\n"
            f"  The scope-drift guard is not running for phase {phase}. "
            f"Add git to PATH before continuing."
        )
        return 0

    if not entries:
        return 0

    drifted: list[hu.DiffEntry] = []
    for entry in entries:
        if entry.status == "??" and scope.allow_untracked_new:
            if any(entry.path.startswith(p) for p in scope.prefixes):
                continue
        if hu.path_in_scope(entry.path, scope, phase):
            continue
        drifted.append(entry)

    if not drifted:
        return 0

    lines = [
        f"SCOPE_DRIFT: files changed outside Phase {phase} ({scope.phase_name}) declared scope:"
    ]
    for d in drifted:
        lines.append(f"  [{d.status or '??'}] {d.path}")
    lines.append(
        "Decide: "
        "(a) accept drift — update plan/phase_{n}_scope.json to include these paths, "
        "(b) revert the changes, "
        "(c) amend and continue with an explicit justification in BUILD_LOG.".format(n=phase)
    )
    hu.emit_stderr_warning("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never block a user edit because of a hook bug.
        sys.exit(0)
