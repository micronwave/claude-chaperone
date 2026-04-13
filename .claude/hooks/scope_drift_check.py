#!/usr/bin/env python3
"""
scope_drift_check.py — PostToolUse hook for Edit / Write / NotebookEdit.

Reads the active phase from plan/current_phase.txt and the scope contract
from plan/phase_<N>_scope.json, then compares against `git status --porcelain`.
Emits a structured warning to stderr for any file outside the declared scope.

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
    # Drain stdin even if we don't use the payload — avoids SIGPIPE on the
    # producer side on some platforms.
    _ = hu.read_hook_payload()

    phase = hu.read_current_phase()
    if phase is None:
        # Workflow not active — silent, no enforcement
        return 0

    try:
        scope = hu.load_phase_scope(phase)
    except hu.ScopeError as exc:
        # LOUD: config error, surface it so the user fixes the scope file
        hu.emit_stderr_warning(
            f"SCOPE_DRIFT_HOOK_ERROR: {exc}\n"
            f"  The scope-drift guard is not running for phase {phase}. "
            f"Fix the scope file before continuing.\n"
            f"  See .claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md"
        )
        return 0  # non-blocking — do not prevent the edit, just surface the problem

    entries = hu.git_changed_paths()
    if not entries:
        return 0

    drifted: list[hu.DiffEntry] = []
    for entry in entries:
        if entry.status == "??" and scope.allow_untracked_new:
            # Untracked new files — allowed if they fall under a prefix
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
    return 0  # non-blocking — user decides resolution


if __name__ == "__main__":
    sys.exit(main())
