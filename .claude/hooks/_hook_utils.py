"""
_hook_utils.py — Shared helpers for claude-build-workflow hooks.

Python 3.8+, stdlib only. Importable as a sibling module by other hook scripts.

Design goals:
- LOUD failures on config errors (emit structured error, do not silently pass)
- Robust to platform differences (Windows path separators, locale)
- Testable: every non-trivial function takes explicit inputs (no global state)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---- Project root discovery --------------------------------------------------

def project_root() -> Path:
    """Return the project root. Prefer $CLAUDE_PROJECT_DIR, fall back to cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


# ---- Phase pointer -----------------------------------------------------------

def read_current_phase(root: Path | None = None) -> int | None:
    """Return the active phase number, or None if the workflow is not active.

    Returns None (not an error) when `plan/current_phase.txt` is absent —
    hooks treat this as "workflow inactive, exit silently".
    """
    root = root or project_root()
    p = root / "plan" / "current_phase.txt"
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


# ---- Scope file loading (LOUD failure mode) ----------------------------------

class ScopeError(Exception):
    """Raised for any config problem with a phase scope JSON file."""
    code: str = "SCOPE_ERROR"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class PhaseScope:
    schema_version: int
    phase_number: int
    phase_name: str
    files: frozenset[str]
    prefixes: tuple[str, ...]
    allow_untracked_new: bool


SUPPORTED_SCHEMA_VERSIONS = {1}


def load_phase_scope(phase_num: int, root: Path | None = None) -> PhaseScope:
    """Load and validate plan/phase_<N>_scope.json.

    Raises ScopeError with a specific code on any failure — never silently
    returns an empty/permissive scope.
    """
    root = root or project_root()
    path = root / "plan" / f"phase_{phase_num}_scope.json"

    if not path.exists():
        raise ScopeError(
            "MISSING_SCOPE_FILE",
            f"expected {path.relative_to(root) if path.is_relative_to(root) else path}",
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScopeError("SCOPE_READ_ERROR", str(exc)) from exc

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScopeError(
            "MALFORMED_SCOPE_JSON",
            f"{exc.msg} at line {exc.lineno} col {exc.colno}",
        ) from exc

    if not isinstance(data, dict):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "top-level value is not an object")

    sv = data.get("schema_version")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        raise ScopeError(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"got {sv!r}, supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}",
        )

    pn = data.get("phase_number")
    if not isinstance(pn, int):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "phase_number must be an integer")
    if pn != phase_num:
        raise ScopeError(
            "SCOPE_PHASE_MISMATCH",
            f"scope JSON says phase_number={pn} but current_phase.txt says {phase_num}",
        )

    name = data.get("phase_name")
    if not isinstance(name, str) or not name.strip():
        raise ScopeError("INVALID_SCOPE_SCHEMA", "phase_name must be a non-empty string")

    scope = data.get("scope")
    if not isinstance(scope, dict):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "scope must be an object")

    files = scope.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "scope.files must be an array of strings")

    prefixes = scope.get("prefixes")
    if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "scope.prefixes must be an array of strings")

    for p in prefixes:
        if not p.endswith("/"):
            raise ScopeError(
                "INVALID_PREFIX",
                f"prefix {p!r} must end in '/' to avoid ambiguous matches",
            )

    allow_new = scope.get("allow_untracked_new", False)
    if not isinstance(allow_new, bool):
        raise ScopeError("INVALID_SCOPE_SCHEMA", "scope.allow_untracked_new must be a boolean")

    return PhaseScope(
        schema_version=sv,
        phase_number=pn,
        phase_name=name,
        files=frozenset(_normalize_path(f) for f in files),
        prefixes=tuple(_normalize_path(p, is_prefix=True) for p in prefixes),
        allow_untracked_new=allow_new,
    )


# ---- Path handling -----------------------------------------------------------

def _normalize_path(p: str, is_prefix: bool = False) -> str:
    """Normalize to forward slashes, strip leading './'. Prefixes keep trailing slash."""
    p = p.replace("\\", "/").strip()
    if p.startswith("./"):
        p = p[2:]
    # Preserve trailing slash on prefixes (required for unambiguous matching)
    return p


def universal_allowlist(phase_num: int) -> frozenset[str]:
    """Paths that are always allowed — workflow metadata files."""
    return frozenset(
        {
            "BUILD_LOG.md",
            "plan/current_phase.txt",
            "plan/workflow_complete.txt",
            "plan/.build_log_reminder_state",
            f"plan/phase_{phase_num}_audit_fix.md",
            f"plan/phase_{phase_num}_handoff.md",
            f"plan/phase_{phase_num}_loop.txt",
            f"plan/phase_{phase_num}_escalation.md",
            f"plan/phase_{phase_num}_scope.json",
        }
    )


def path_in_scope(changed_path: str, scope: PhaseScope, phase_num: int) -> bool:
    """Return True if changed_path is allowed under the given scope."""
    p = _normalize_path(changed_path)

    if p in universal_allowlist(phase_num):
        return True
    if p in scope.files:
        return True
    for prefix in scope.prefixes:
        if p.startswith(prefix):
            return True
    return False


# ---- Git diff ----------------------------------------------------------------

@dataclass(frozen=True)
class DiffEntry:
    status: str  # 'M', 'A', 'D', 'R', '??', etc.
    path: str


def git_changed_paths(root: Path | None = None) -> list[DiffEntry]:
    """Return all changed paths (staged, unstaged, untracked).

    Uses `git status --porcelain=v1 -z` to avoid quoting edge cases.
    Returns an empty list on any git failure — distinct from "no changes"
    only at the level of log messages; both are treated as "nothing to check".
    """
    root = root or project_root()
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            capture_output=True,
            timeout=10,
            cwd=str(root),
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []

    # Porcelain v1 -z output: each entry is "<XY> <path>\0" (or rename "<XY> <new>\0<old>\0")
    raw = out.stdout.decode("utf-8", errors="replace")
    entries: list[DiffEntry] = []
    i = 0
    parts = raw.split("\x00")
    # parts ends with empty string after last NUL
    while i < len(parts):
        item = parts[i]
        if not item:
            i += 1
            continue
        if len(item) < 3:
            i += 1
            continue
        status = item[:2].strip()
        path = item[3:]
        entries.append(DiffEntry(status=status, path=_normalize_path(path)))
        # For renames (R/C), the NEXT entry is the old path — consume it too
        if status.startswith(("R", "C")):
            i += 1
            if i < len(parts) and parts[i]:
                entries.append(
                    DiffEntry(status="D_rename_source", path=_normalize_path(parts[i]))
                )
        i += 1
    return entries


# ---- Stdin payload parsing ---------------------------------------------------

def read_hook_payload() -> dict[str, Any]:
    """Read and parse the JSON payload Claude Code passes on stdin.

    Returns {} on any parse failure — downstream code decides whether that
    is acceptable. Never raises.
    """
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def get_tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    ti = payload.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def get_tool_name(payload: dict[str, Any]) -> str:
    tn = payload.get("tool_name")
    return tn if isinstance(tn, str) else ""


# ---- Structured output helpers ----------------------------------------------

def emit_permission_ask(reason: str) -> None:
    """Emit PreToolUse JSON that forces the permission prompt with a reason."""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def emit_permission_deny(reason: str) -> None:
    """Emit PreToolUse JSON that denies with a reason."""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def emit_stderr_warning(message: str) -> None:
    """Emit a non-blocking warning to stderr. Hook should still exit 0."""
    sys.stderr.write(message)
    if not message.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def emit_additional_context(message: str) -> None:
    """Emit UserPromptSubmit structured JSON that injects additional context
    into Claude's next response.

    Per the Claude Code hook spec, UserPromptSubmit stdout is one of the
    channels that is actually added to Claude's conversation context (the
    other being SessionStart; see `emit_session_start_context`). Stop-hook
    stdout prints to the user's terminal but is NOT seen by Claude — a
    common pitfall. Use this helper for any UserPromptSubmit hook whose
    purpose is to nudge the agent, not just the human.
    """
    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": message,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def emit_session_start_context(message: str) -> None:
    """Emit SessionStart structured JSON that injects additional context
    into Claude's conversation at session start.

    Per the Claude Code hook spec, SessionStart stdout is added to Claude's
    context the same way UserPromptSubmit is — the only difference is the
    hookEventName field. Fires on new session, resume, AND after /clear
    (distinguished by the payload's `source` field, which we don't consult:
    the state snapshot is the same regardless of trigger).
    """
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


# ---- Git push detection ------------------------------------------------------

_PUSH_REGEX = re.compile(
    r"""
    (?:^|[\s;&|`(]|&&|\|\|)          # command boundary: start, whitespace, separators, subshell open, backtick
    (?:\w+=\S+\s+)*                  # optional env var prefixes (VAR=val)
    ["']?                            # optional opening quote
    (?:\.[\\/])?                     # optional ./
    git(?:\.exe)?                    # git or git.exe
    ["']?                            # optional closing quote
    \s+                              # whitespace between git and subcommand
    push                             # literal "push"
    (?:\s|$|["'<>|&;)`])             # end boundary: word boundary, shell token, subshell close, or backtick
    """,
    re.IGNORECASE | re.VERBOSE,
)


def command_contains_git_push(cmd: str) -> bool:
    """Return True if cmd contains a `git push` invocation anywhere.

    Handles:
    - `git push` (basic)
    - `git push origin main --force`
    - `GIT_ASKPASS=foo git push`
    - `cd x && git push`
    - `"git" push`
    - `git.exe push` (Windows)
    - piped/chained: `foo | bar; git push`

    Does NOT match:
    - `pushd` (shell builtin)
    - `git pushx` (hypothetical non-push subcommand)
    - `# git push` (comments — note: still matches because shell comments
       aren't evaluated in our regex context; this is a conservative false-positive
       that surfaces a permission prompt, never a silent pass-through)
    """
    if not cmd:
        return False
    return bool(_PUSH_REGEX.search(cmd))
