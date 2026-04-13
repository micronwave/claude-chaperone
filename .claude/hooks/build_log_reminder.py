#!/usr/bin/env python3
"""
build_log_reminder.py — UserPromptSubmit hook.

When the user submits a prompt, if the workflow is active and code files have
been modified without a corresponding BUILD_LOG.md update, inject a reminder
into Claude's next turn via the structured `additionalContext` JSON channel.

Why UserPromptSubmit and not Stop?
    Per the Claude Code hook spec, Stop-hook stdout prints to the user's
    terminal but is NOT added to Claude's conversation context. Only
    UserPromptSubmit and SessionStart can inject context Claude will see.
    A "remind the agent to update BUILD_LOG" hook therefore has to fire on
    UserPromptSubmit to actually reach its intended audience.

Delivery channels (double-write for robustness):
    1. Structured JSON on stdout (`hookSpecificOutput.additionalContext`) —
       primary channel, documented as the forward-compatible API. This is
       what Claude reads on its next turn.
    2. stderr — secondary, so the human sees the same reminder in transcript
       mode even if the structured-JSON injection has issues in a given
       Claude Code version (see github.com/anthropics/claude-code/issues/13912).

Non-blocking: always exits 0. Never rejects the user's prompt.
"""
from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import _hook_utils as hu  # noqa: E402


REMINDER_MESSAGE = (
    "REMINDER: files changed but BUILD_LOG.md not updated.\n"
    "  - Append a log entry describing the change if work is ongoing.\n"
    "  - Run /wrap to finalize and commit this phase."
)


def main() -> int:
    # Payload is read but not strictly required — we only need filesystem state.
    hu.read_hook_payload()

    phase = hu.read_current_phase()
    if phase is None:
        return 0  # workflow inactive — no reminders

    entries = hu.git_changed_paths()
    if not entries:
        return 0

    # Paths that, on their own, don't constitute a code change requiring a log.
    allowlist = hu.universal_allowlist(phase) | {
        "plan/meta.md",
        "plan/plan.md",
        "plan/plan_audit.md",
    }
    code_changes = [
        e
        for e in entries
        if e.path not in allowlist
        and not e.path.startswith("plan/")
        and e.path != "BUILD_LOG.md"
    ]
    if not code_changes:
        return 0

    if any(e.path == "BUILD_LOG.md" for e in entries):
        return 0  # already logged this cycle

    # Primary: inject into Claude's context for its next turn.
    hu.emit_additional_context(REMINDER_MESSAGE)
    # Secondary: surface to the user in transcript mode (Ctrl-R).
    hu.emit_stderr_warning(REMINDER_MESSAGE)
    return 0  # non-blocking


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never block a user prompt because of a hook bug.
        sys.exit(0)
