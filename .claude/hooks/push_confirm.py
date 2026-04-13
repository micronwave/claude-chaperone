#!/usr/bin/env python3
"""
push_confirm.py — PreToolUse hook for Bash.

Forces a user permission prompt for any `git push` invocation by emitting the
structured JSON output per Claude Code hook spec:

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "<why>"
      }
    }

Why "ask" instead of "deny":
    Push is destructive to the shared remote but legitimate many times per
    session. "ask" gives the user one-click approval per push. "deny" would
    require disabling the hook to push at all.

Non-goals:
    - This hook does NOT try to detect `git push` hidden behind shell aliases
      or custom wrappers. Defense in depth is the responsibility of the
      permission system.

Exit behavior:
    - Always exits 0 (structured output is the communication channel, not the
      exit code, when using JSON responses).
    - On any internal error: exits 0 silently. Failing loud on the push guard
      would block legitimate commands on an unrelated bug; failing silent here
      is the safer default because the permission system is a backstop.
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
    if not payload:
        return 0  # empty stdin or parse failure — no-op

    # Narrow to Bash tool events
    if hu.get_tool_name(payload) != "Bash":
        return 0

    cmd = hu.get_tool_input(payload).get("command", "")
    if not isinstance(cmd, str) or not cmd:
        return 0

    if not hu.command_contains_git_push(cmd):
        return 0

    hu.emit_permission_ask(
        "git push is destructive to the shared remote. "
        "Review the command and confirm before proceeding. "
        "(push_confirm hook from claude-build-workflow)"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never let an internal error break the user's session.
        # The permission system will still challenge the push if configured to.
        sys.exit(0)
