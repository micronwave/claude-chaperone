#!/usr/bin/env python3
"""claude-chaperone installer (v0 minimal).

Copies the chaperone artifacts into a target project, merges settings.json
without clobbering user-owned hooks, and injects a marker block into
CLAUDE.md exactly once. Idempotent — re-run any time to re-sync.

Usage:
    python install.py --target DIR
    curl -sSL .../install.py | python - --target .

Exit codes:
    0 — success
    1 — user error (bad target, unresolved conflict, corrupt target JSON)
    2 — system error (network, permission, corrupt upstream JSON)
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = "0.1.0"

# --- Manifests --------------------------------------------------------
# Hardcoded because curl-mode cannot enumerate a remote tree. Kept identical
# to deferred-plans/INSTALLER_PLAN.md so the v1.0 upgrade is additive.

COMMANDS: List[str] = [
    ".claude/commands/build.md",
    ".claude/commands/build-audit.md",
    ".claude/commands/chaperone.md",
    ".claude/commands/execute.md",
    ".claude/commands/handoff.md",
    ".claude/commands/meta-prompt.md",
    ".claude/commands/phase-audit.md",
    ".claude/commands/plan.md",
    ".claude/commands/plan-audit.md",
    ".claude/commands/re-audit.md",
    ".claude/commands/split-phases.md",
    ".claude/commands/test.md",
    ".claude/commands/wrap.md",
]

HOOKS_REGISTERED: List[str] = [
    ".claude/hooks/push_confirm.py",
    ".claude/hooks/scope_drift_check.py",
    ".claude/hooks/build_log_reminder.py",
    ".claude/hooks/session_start.py",
]

HOOKS_SUPPORT: List[str] = [
    ".claude/hooks/_hook_utils.py",
    ".claude/hooks/test_hooks.py",
    ".claude/hooks/README.md",
]

SKILLS: List[str] = [
    ".claude/skills/full-build-workflow/SKILL.md",
    ".claude/skills/full-build-workflow/references/prompts/audit-prompt.md",
    ".claude/skills/full-build-workflow/references/prompts/build-prompt.md",
    ".claude/skills/full-build-workflow/references/prompts/meta-prompt.md",
    ".claude/skills/full-build-workflow/references/prompts/plan-prompt.md",
    ".claude/skills/full-build-workflow/references/templates/audit_fix.md",
    ".claude/skills/full-build-workflow/references/templates/bootstrap.md",
    ".claude/skills/full-build-workflow/references/templates/build_log.md",
    ".claude/skills/full-build-workflow/references/templates/handoff.md",
    ".claude/skills/full-build-workflow/references/templates/phase_scope.json",
    ".claude/skills/full-build-workflow/references/templates/plan.md",
    ".claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md",
]

ALL_ARTIFACTS: List[str] = COMMANDS + HOOKS_REGISTERED + HOOKS_SUPPORT + SKILLS

# Documented exclusions (we enumerate instead of walking, but noted here so
# behavior stays identical if a future version switches to a walker).
EXCLUDED_BASENAMES = {"settings.local.json"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_DIRNAMES = {"__pycache__"}

# Authoritative hook -> event mapping. Must match source settings.json.
HOOK_REGISTRATIONS = {
    "push_confirm.py":       ("PreToolUse",       "Bash",                    "Bash(git push*)"),
    "scope_drift_check.py":  ("PostToolUse",      "Edit|Write|NotebookEdit", None),
    "build_log_reminder.py": ("UserPromptSubmit", "",                        None),
    "session_start.py":      ("SessionStart",     "",                        None),
}

BEGIN_MARKER_FMT = "<!-- BEGIN claude-chaperone v{version} -->"
END_MARKER = "<!-- END claude-chaperone -->"
# END is intentionally unversioned so the regex works across versions.
MARKER_RE = re.compile(
    r"<!-- BEGIN claude-chaperone(?: v[^ ]+)? -->.*?<!-- END claude-chaperone -->",
    re.DOTALL,
)
# Matches a standalone BEGIN marker (with or without version). Used to detect
# unterminated BEGIN markers that lack a corresponding END.
_BEGIN_ONLY_RE = re.compile(r"<!-- BEGIN claude-chaperone(?: v[^ ]+)? -->")
# Matches the BEGIN marker with or without a version tag. Used to strip the
# version so content-equality comparisons survive a __version__ bump.
_BEGIN_MARKER_STRIP_RE = re.compile(r"<!-- BEGIN claude-chaperone(?: v[^ ]+)? -->")

# --- Source resolution (clone vs. curl) -------------------------------

try:
    # resolve() follows symlinks so a symlinked install.py (e.g., dev
    # convenience linking to a clone) still resolves SRC_DIR to the clone
    # root — otherwise is_clone_mode() returns False and we'd silently fall
    # through to network fetch mode.
    SRC_DIR: Optional[Path] = Path(__file__).resolve().parent
except NameError:
    # `curl | python -` — __file__ is undefined on CPython 3.8+.
    SRC_DIR = None


def is_clone_mode() -> bool:
    return SRC_DIR is not None and (SRC_DIR / "settings.json").is_file()


# Allowlist for CHAPERONE_REF. A git ref is a branch, tag, or commit SHA; the
# subset below covers those while refusing anything that could redirect the
# fetch URL (e.g., path-traversal, query strings, schemes).
_REF_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_ref(ref: str) -> str:
    if (
        not ref
        or not _REF_ALLOWED_RE.match(ref)
        or ".." in ref
        or ref.startswith("/")
        or ref.endswith("/")
        or ref.startswith(".")
    ):
        die_user(
            f"invalid CHAPERONE_REF {ref!r}: expected a git branch/tag/SHA "
            "matching [A-Za-z0-9._/-]+ with no '..' or leading '.' or '/'"
        )
    return ref


def raw_url(ref: str, path: str) -> str:
    path = path.replace(os.sep, "/")
    return f"https://raw.githubusercontent.com/micronwave/claude-chaperone/{ref}/{path}"


def fetch_bytes(rel_path: str) -> bytes:
    """Fetch an upstream artifact as bytes, from clone or curl.

    Always returns LF-normalized bytes. The manifest is all text (.md/.py/.json),
    and installer-produced files are LF-only regardless of how the source got its
    line endings (Windows git autocrlf, editor rewrites). This keeps byte-equality
    stable across re-runs.
    """
    if is_clone_mode():
        src = SRC_DIR / rel_path  # type: ignore[operator]
        try:
            data = src.read_bytes()
        except OSError as e:
            die_sys(f"cannot read source file {src}: {e}")
    else:
        ref = _validate_ref(os.environ.get("CHAPERONE_REF", "main"))
        url = raw_url(ref, rel_path)
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as e:
            die_sys(f"failed to fetch {url}: {e}")
    return data.replace(b"\r\n", b"\n")


def fetch_text(rel_path: str) -> str:
    try:
        return fetch_bytes(rel_path).decode("utf-8")
    except UnicodeDecodeError as e:
        die_sys(f"{rel_path} is not valid UTF-8: {e}")


# --- Error helpers ----------------------------------------------------

def die_user(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def die_sys(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


# --- Atomic writes ----------------------------------------------------

def _atomic_replace(path: Path, mode: str, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die_sys(f"cannot create directory {path.parent}: {e}")
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
    except OSError as e:
        die_sys(f"cannot create temp file in {path.parent}: {e}")

    # `replaced` tracks whether os.replace() consumed the tmp file. If it
    # didn't (any exception path — including KeyboardInterrupt or the
    # SystemExit raised by die_sys), the finally clause removes the leftover.
    replaced = False
    try:
        try:
            # os.fdopen itself is assumed to succeed; a failure here implies a
            # broken Python install (e.g., missing utf-8 codec) and is out of
            # scope — the raw fd would leak in that case, but cleanup is not
            # feasible without reimplementing fdopen's error paths.
            if "b" in mode:
                with os.fdopen(fd, mode) as f:
                    f.write(data)
            else:
                with os.fdopen(fd, mode, encoding="utf-8", newline="") as f:
                    f.write(data)
            os.replace(tmp_name, path)
            replaced = True
        except OSError as e:
            die_sys(f"cannot write {path}: {e}")
    finally:
        if not replaced:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def atomic_write_text(path: Path, text: str) -> None:
    _atomic_replace(path, "w", text)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    _atomic_replace(path, "wb", data)


# --- Artifact copy ----------------------------------------------------

def plan_copy_artifacts(
    target: Path, force: bool
) -> Tuple[List[Tuple[str, str, Optional[bytes]]], List[str]]:
    """Plan every manifest-file copy. No writes.

    Returns (pending, conflicts).
        pending:   list of (action, rel, data-or-None) where action is "new" | "same" | "over"
        conflicts: list of rel_paths that differed from upstream without --force
    """
    pending: List[Tuple[str, str, Optional[bytes]]] = []
    conflicts: List[str] = []

    for rel in ALL_ARTIFACTS:
        src_data = fetch_bytes(rel)  # already LF-normalized
        dst = target / rel
        if not dst.exists():
            pending.append(("new", rel, src_data))
            continue
        try:
            existing = dst.read_bytes()
        except OSError as e:
            die_sys(f"cannot read existing file {dst}: {e}")
        # Normalize target CRLF -> LF so Windows editors / git autocrlf don't
        # flag unchanged content as drift. Source is already LF-normalized.
        if existing.replace(b"\r\n", b"\n") == src_data:
            pending.append(("same", rel, None))
        elif force:
            pending.append(("over", rel, src_data))
        else:
            conflicts.append(rel)

    return pending, conflicts


def apply_copy_artifacts(
    target: Path, pending: List[Tuple[str, str, Optional[bytes]]]
) -> List[Tuple[str, str]]:
    """Execute the pending artifact writes."""
    report: List[Tuple[str, str]] = []
    for action, rel, data in pending:
        if action in ("new", "over") and data is not None:
            atomic_write_bytes(target / rel, data)
        report.append((action, rel))
    return report


# --- settings.json merge ---------------------------------------------

def _find_matcher_block(arr, matcher: str) -> Optional[dict]:
    # Equality match on matcher — including "" for UserPromptSubmit. Must NOT
    # be `if block.get("matcher"):`, which would silently skip empty matchers.
    for block in arr:
        if isinstance(block, dict) and block.get("matcher") == matcher:
            return block
    return None


def _find_hook_entry_index(block: dict, script_name: str) -> Optional[int]:
    # Identify the hooks entry that invokes `.claude/hooks/<script_name>`.
    #
    # Approach: shlex-tokenize the command and check each token. Rejects any
    # token that isn't itself a path — only path-shaped tokens match, so a
    # hook entry whose `command` contains the path inside a multi-word
    # argument is never misidentified. Within a token, we also require the
    # path to start at a non-identifier boundary so `foo.claude/hooks/X.py`
    # doesn't spuriously match.
    #
    # This accepts the common invocation shapes:
    #   python "$CLAUDE_PROJECT_DIR"/.claude/hooks/X.py
    #   python ".claude/hooks/X.py"
    #   python /abs/path/.claude/hooks/X.py
    # And rejects multi-word quoted strings (tokens containing whitespace
    # after shlex), unrelated suffix matches like `X.py.backup` or
    # `push_confirm_custom.py`, and identifier-prefixed paths like
    # `foo.claude/hooks/X.py`.
    #
    # Windows users who hand-edited settings.json with backslashes still
    # match because we normalize separators before tokenizing. An unbalanced
    # quote falls back to whitespace split so a malformed command can't
    # crash the installer.
    path_tail_re = re.compile(
        r"(?:^|(?<=[^A-Za-z0-9_]))\.claude/hooks/" + re.escape(script_name) + r"$"
    )

    for i, h in enumerate(block.get("hooks", [])):
        if not isinstance(h, dict):
            continue
        cmd = h.get("command", "")
        if not isinstance(cmd, str):
            continue
        cmd_norm = cmd.replace("\\", "/")
        try:
            tokens = shlex.split(cmd_norm, posix=True)
        except ValueError:
            tokens = cmd_norm.split()
        for t in tokens:
            if " " in t or "\t" in t:
                continue
            if path_tail_re.search(t):
                return i
    return None


def plan_merge_settings(target: Path) -> Dict[str, Any]:
    """Parse + validate upstream and target settings.json. No writes.

    Dies (die_user / die_sys) on any malformed input so downstream writes
    don't have to worry about user errors. Returns a plan dict carrying the
    parsed JSON plus the target path.
    """
    src_text = fetch_text("settings.json")
    try:
        src_settings = json.loads(src_text)
    except json.JSONDecodeError as e:
        die_sys(f"upstream settings.json is not valid JSON: {e}")
    if not isinstance(src_settings, dict):
        die_sys(
            "upstream settings.json must be a JSON object "
            f"(got {type(src_settings).__name__})"
        )
    if "hooks" in src_settings and not isinstance(src_settings["hooks"], dict):
        die_sys(
            "upstream settings.json 'hooks' must be an object "
            f"(got {type(src_settings['hooks']).__name__})"
        )

    tgt_path = target / ".claude" / "settings.json"
    if tgt_path.exists():
        try:
            raw = tgt_path.read_text(encoding="utf-8")
        except OSError as e:
            die_sys(f"cannot read {tgt_path}: {e}")
        except UnicodeDecodeError as e:
            die_user(
                f"target settings.json is not valid UTF-8 ({e}); "
                "fix or remove it before re-running"
            )
        try:
            tgt_settings = json.loads(raw)
        except json.JSONDecodeError as e:
            die_user(
                f"target settings.json is not valid JSON ({e}); "
                "fix or remove it before re-running"
            )
    else:
        tgt_settings = {}

    if not isinstance(tgt_settings, dict):
        die_user(
            "target settings.json must be a JSON object at the top level "
            f"(got {type(tgt_settings).__name__}); fix or remove it before re-running"
        )
    if "hooks" in tgt_settings and not isinstance(tgt_settings["hooks"], dict):
        die_user(
            "target settings.json 'hooks' must be an object "
            f"(got {type(tgt_settings['hooks']).__name__}); "
            "fix or remove it before re-running"
        )

    # Pre-validate target event arrays + duplicate matcher blocks. Doing this
    # up-front prevents a malformed target from silently papering over two
    # matcher blocks with the same string (`_find_matcher_block` only finds
    # the first, so later duplicates would be ignored during apply).
    tgt_hooks_pre = tgt_settings.get("hooks", {})
    events_touched = {HOOK_REGISTRATIONS[Path(r).name][0] for r in HOOKS_REGISTERED}
    for event in events_touched:
        if event not in tgt_hooks_pre:
            continue
        arr = tgt_hooks_pre[event]
        if not isinstance(arr, list):
            die_user(
                f"target settings.json hooks.{event} must be an array "
                f"(got {type(arr).__name__}); fix or remove it before re-running"
            )
        seen_matchers: Dict[Any, int] = {}
        for block in arr:
            if not isinstance(block, dict):
                continue
            m = block.get("matcher")
            seen_matchers[m] = seen_matchers.get(m, 0) + 1
        dupes = [m for m, n in seen_matchers.items() if n > 1]
        if dupes:
            shown = ", ".join(repr(m) for m in dupes)
            die_user(
                f"target settings.json hooks.{event} has duplicate matcher "
                f"block(s) for {shown}; merge them by hand before re-running"
            )

        # The matcher block we'll touch (if present) must have a list-typed
        # 'hooks' field.
        for script_rel in HOOKS_REGISTERED:
            script_name = Path(script_rel).name
            ev, matcher, _if = HOOK_REGISTRATIONS[script_name]
            if ev != event:
                continue
            block = _find_matcher_block(arr, matcher)
            if block is not None and not isinstance(block.get("hooks", []), list):
                die_user(
                    f"target settings.json hooks.{event} matcher={matcher!r} "
                    f"has a non-array 'hooks' field; fix or remove it before re-running"
                )

    return {
        "src_settings": src_settings,
        "tgt_settings": tgt_settings,
        "tgt_path": tgt_path,
    }


def apply_merge_settings(plan: Dict[str, Any], force: bool) -> List[Tuple[str, str]]:
    """Execute a validated settings merge.

    Returns list of (status, label) where status is "add" | "skip" | "over".
    """
    src_settings = plan["src_settings"]
    tgt_settings = plan["tgt_settings"]
    tgt_path = plan["tgt_path"]

    # Preserve any existing top-level $comment. If the target has none, copy
    # the upstream one (useful when creating settings.json from scratch).
    if "$comment" not in tgt_settings and "$comment" in src_settings:
        tgt_settings["$comment"] = src_settings["$comment"]

    tgt_hooks = tgt_settings.setdefault("hooks", {})
    src_hooks = src_settings.get("hooks", {})

    report: List[Tuple[str, str]] = []

    for script_rel in HOOKS_REGISTERED:
        script_name = Path(script_rel).name
        event, matcher, _if_field = HOOK_REGISTRATIONS[script_name]

        # Locate upstream block + entry (authoritative templates).
        src_arr = src_hooks.get(event, [])
        src_block = _find_matcher_block(src_arr, matcher)
        if src_block is None:
            die_sys(
                f"upstream settings.json missing {event} matcher={matcher!r}; "
                "installer/upstream out of sync"
            )
        src_entry_idx = _find_hook_entry_index(src_block, script_name)
        if src_entry_idx is None:
            die_sys(
                f"upstream settings.json {event}/{matcher!r} missing hook for "
                f"{script_name}; installer/upstream out of sync"
            )
        src_entry = src_block["hooks"][src_entry_idx]

        # Locate (or create) target event array and matcher block.
        tgt_arr = tgt_hooks.setdefault(event, [])
        tgt_block = _find_matcher_block(tgt_arr, matcher)
        if tgt_block is None:
            tgt_block = {"matcher": matcher, "hooks": []}
            # Copy $comment only when creating a new block. We don't rewrite
            # existing blocks' $comment in v0.
            if "$comment" in src_block:
                tgt_block["$comment"] = src_block["$comment"]
            tgt_arr.append(tgt_block)

        tgt_hook_list = tgt_block.setdefault("hooks", [])
        tgt_entry_idx = _find_hook_entry_index(tgt_block, script_name)

        matcher_display = '""' if matcher == "" else matcher
        label = f"{event} > {matcher_display} > {script_name}"

        if tgt_entry_idx is None:
            tgt_hook_list.append(src_entry)
            report.append(("add", label))
        elif force:
            # Replace the entire entry (not just `command`) so the `if` field
            # gets re-synced rather than silently drifting.
            tgt_hook_list[tgt_entry_idx] = src_entry
            report.append(("over", label))
        else:
            report.append(("skip", label))

    # ensure_ascii=False preserves any Unicode the user placed in $comment or
    # other string values; with the default True, on every rerun those would
    # be re-encoded as \uXXXX escapes and registered as a diff even when
    # semantically identical.
    out_text = json.dumps(tgt_settings, indent=2, ensure_ascii=False) + "\n"

    # Diff-first, CRLF-tolerant: normalize target line endings before comparing
    # to the serialized LF output, so a CRLF target (Windows editor rewrite or
    # git autocrlf) doesn't force a rewrite on every re-run. We read bytes so
    # the decode step doesn't apply platform newline translation, then do the
    # CRLF->LF fold explicitly — mirroring the artifact-copy logic above.
    if tgt_path.exists():
        try:
            current_bytes = tgt_path.read_bytes()
        except OSError:
            current_bytes = None
        if current_bytes is not None:
            try:
                current = current_bytes.replace(b"\r\n", b"\n").decode("utf-8")
            except UnicodeDecodeError:
                current = None
            if current == out_text:
                return report
    atomic_write_text(tgt_path, out_text)
    return report


# --- CLAUDE.md injection ---------------------------------------------

def _strip_snippet_header(snippet: str) -> str:
    """Strip leading lines up to and including the first blank line.

    Removes the `# Paste this section into your project's CLAUDE.md` header
    so downstream users don't see that instruction in their CLAUDE.md.
    """
    lines = snippet.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == "":
            return "".join(lines[i + 1:])
    # No blank line anywhere — nothing to strip.
    return snippet


def _norm_marker(s: str) -> str:
    # Normalize for comparison: strip surrounding whitespace and CRLF so
    # trailing newlines / line-ending drift don't register as content drift.
    return s.strip().replace("\r\n", "\n")


def _norm_marker_versionless(s: str) -> str:
    # Additionally strip the version tag from the BEGIN marker, so a
    # __version__ bump with identical body content compares equal.
    return _BEGIN_MARKER_STRIP_RE.sub(
        "<!-- BEGIN claude-chaperone -->", _norm_marker(s)
    )


def plan_inject_claude_md(target: Path, force: bool) -> Dict[str, Any]:
    """Plan CLAUDE.md injection. No writes.

    Returns a plan dict with 'status' one of:
        "add"            — no marker block present; append at EOF
        "same"           — single marker block present and matches canonical
        "resync"         — single marker block matches body but version tag differs; silent re-sync
        "replace"        — single marker block differs in body; will be replaced (force)
        "replace-multi"  — multiple marker blocks present; first replaced + rest dropped (force)
        "conflict"       — content mismatch (no --force), multiple blocks (no --force),
                           or unterminated BEGIN marker (--force cannot fix)
    """
    snippet_raw = fetch_text("CLAUDE.md.snippet")
    body = _strip_snippet_header(snippet_raw).strip("\n")

    begin = BEGIN_MARKER_FMT.format(version=__version__)
    block = f"{begin}\n{body}\n{END_MARKER}\n"

    tgt_path = target / "CLAUDE.md"
    if tgt_path.exists():
        try:
            existing = tgt_path.read_text(encoding="utf-8")
        except OSError as e:
            die_sys(f"cannot read {tgt_path}: {e}")
        except UnicodeDecodeError as e:
            die_user(
                f"target CLAUDE.md is not valid UTF-8 ({e}); "
                "fix or remove it before re-running"
            )
    else:
        existing = ""

    matches = list(MARKER_RE.finditer(existing))

    # Detect unterminated BEGIN markers: a BEGIN without a matching END means
    # a prior install aborted mid-write, a bad merge, or a hand-edit. The
    # complete MARKER_RE won't match these, so we count standalone BEGINs
    # separately and compare.
    begin_count = len(_BEGIN_ONLY_RE.findall(existing))

    plan: Dict[str, Any] = {
        "tgt_path": tgt_path,
        "existing": existing,
        "block": block,
        "matches": matches,
    }

    if begin_count > len(matches):
        plan["status"] = "conflict"
        plan["conflict_reason"] = "unterminated"
        return plan

    if not matches:
        plan["status"] = "add"
        return plan

    if len(matches) == 1:
        existing_block = matches[0].group(0)
        if _norm_marker(existing_block) == _norm_marker(block):
            plan["status"] = "same"
            return plan
        if _norm_marker_versionless(existing_block) == _norm_marker_versionless(block):
            # Only the BEGIN marker's version tag differs; body is identical.
            # Re-sync silently so __version__ bumps don't force the user into
            # --force on an otherwise idempotent rerun.
            plan["status"] = "resync"
            return plan
        if not force:
            plan["status"] = "conflict"
            plan["conflict_reason"] = "differs"
            return plan
        plan["status"] = "replace"
        return plan

    # len(matches) > 1: always worth surfacing regardless of content — the
    # "exactly once" invariant is violated.
    if not force:
        plan["status"] = "conflict"
        plan["conflict_reason"] = "multiple"
        return plan
    plan["status"] = "replace-multi"
    plan["match_count"] = len(matches)
    return plan


def apply_inject_claude_md(plan: Dict[str, Any]) -> Tuple[str, Optional[int]]:
    """Execute a validated CLAUDE.md plan. Returns (status, line).

    status: "add" | "same" | "replace" | "replace-multi" | "resync"
    line:   1-based insertion/replacement line, or None for "same"
    """
    status = plan["status"]
    tgt_path: Path = plan["tgt_path"]
    existing: str = plan["existing"]
    block: str = plan["block"]
    matches = plan["matches"]

    if status == "same":
        return ("same", None)

    if status == "add":
        # Append at EOF with a blank-line separator.
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing and not existing.endswith("\n\n"):
            existing += "\n"
        insertion_line = existing.count("\n") + 1
        atomic_write_text(tgt_path, existing + block)
        return ("add", insertion_line)

    if status in ("replace", "resync"):
        m = matches[0]
        start, end = m.span()
        line_of_replacement = existing.count("\n", 0, start) + 1
        replacement = block.rstrip("\n")
        atomic_write_text(tgt_path, existing[:start] + replacement + existing[end:])
        return (status, line_of_replacement)

    if status == "replace-multi":
        # Replace the first occurrence with the canonical block and drop every
        # later occurrence entirely. Line number reported is where the canonical
        # block now lives (first match's start).
        first_start = matches[0].start()
        line_of_replacement = existing.count("\n", 0, first_start) + 1
        out_parts: List[str] = []
        last_end = 0
        for i, m in enumerate(matches):
            out_parts.append(existing[last_end:m.start()])
            if i == 0:
                out_parts.append(block.rstrip("\n"))
            # else: drop this span
            last_end = m.end()
        out_parts.append(existing[last_end:])
        atomic_write_text(tgt_path, "".join(out_parts))
        return ("replace-multi", line_of_replacement)

    # "conflict" should be filtered by the caller before apply.
    raise RuntimeError(f"apply_inject_claude_md: unexpected status {status!r}")


# --- Version sentinel -------------------------------------------------

def write_version(target: Path) -> None:
    # Idempotent: when the sentinel already records the current version, skip
    # the write so re-runs against a fully-installed target don't bump mtimes
    # or dirty git.
    path = target / ".claude" / ".chaperone-version"
    expected = __version__ + "\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == expected:
                return
        except OSError:
            pass
    atomic_write_text(path, expected)


# --- Post-install test ------------------------------------------------

def run_tests(target: Path) -> Tuple[bool, str]:
    test_script = target / ".claude" / "hooks" / "test_hooks.py"
    if not test_script.is_file():
        return (False, "test_hooks.py missing after install")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(target)
    try:
        proc = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(target),
            env=env,
            capture_output=True,
            text=True,
            # errors="replace" prevents a Windows decode crash when child
            # output contains bytes outside the process's default code page.
            errors="replace",
        )
    except OSError as e:
        return (False, f"failed to invoke test_hooks.py: {e}")
    combined = (proc.stdout or "") + (proc.stderr or "")
    return (proc.returncode == 0, combined.strip())


def _pick_test_summary(out: str) -> str:
    # Look for the conventional unittest summary: "Ran N tests in ... OK/FAILED".
    for line in reversed(out.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("OK") or stripped.startswith("FAILED"):
            return stripped
        if stripped.startswith("Ran ") and "test" in stripped:
            return stripped
        if "passed" in stripped or "failed" in stripped:
            return stripped
    return ""


# --- Main -------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="install.py",
        description="Install claude-chaperone into a target project.",
    )
    p.add_argument(
        "--target",
        default=".",
        help="Target project directory (default: current directory).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite chaperone-owned files and re-sync settings.json / CLAUDE.md.",
    )
    p.add_argument(
        "--skip-tests",
        action="store_true",
        help="Don't run test_hooks.py after install.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    # Single-writer assumption: the installer assumes nothing else is modifying
    # chaperone-owned files, settings.json, or CLAUDE.md between the plan phase
    # and the apply phase. Concurrent edits during install are out of scope; an
    # idempotent re-run after any unexpected state converges to the correct
    # install.
    args = parse_args(argv)

    if sys.version_info < (3, 8):
        die_user(
            f"Python 3.8+ required (have {sys.version_info.major}.{sys.version_info.minor})."
        )

    target = Path(args.target).resolve()
    if not target.exists():
        die_user(f"target does not exist: {target}")
    if not target.is_dir():
        die_user(f"target is not a directory: {target}")

    # Phase 1: plan everything. No filesystem writes in this phase. Validation
    # errors (die_user / die_sys) still abort immediately — those are not
    # recoverable by --force.
    copy_pending, copy_conflicts = plan_copy_artifacts(target, args.force)
    settings_plan = plan_merge_settings(target)
    claude_plan = plan_inject_claude_md(target, args.force)

    # Phase 2: surface every conflict in one pass and abort before touching
    # anything. This preserves atomicity — a CLAUDE.md conflict no longer
    # leaves the target half-installed after copy + settings writes.
    had_conflict = False
    if copy_conflicts:
        print(
            "error: the following chaperone-owned files differ from upstream:",
            file=sys.stderr,
        )
        for rel in copy_conflicts:
            print(f"  {rel}", file=sys.stderr)
        had_conflict = True
    if claude_plan["status"] == "conflict":
        reason = claude_plan.get("conflict_reason", "differs")
        if reason == "unterminated":
            print(
                "error: CLAUDE.md has an unterminated claude-chaperone BEGIN marker "
                "(no matching END). Repair the file by hand or delete the stray "
                "BEGIN, then re-run.",
                file=sys.stderr,
            )
        elif reason == "multiple":
            print(
                "error: CLAUDE.md contains multiple claude-chaperone marker blocks; "
                "the 'exactly once' invariant is violated.",
                file=sys.stderr,
            )
        else:
            print(
                "error: CLAUDE.md has a claude-chaperone marker block that differs "
                "from the upstream snippet.",
                file=sys.stderr,
            )
        had_conflict = True
    if had_conflict:
        claude_reason = claude_plan.get("conflict_reason")
        if claude_reason != "unterminated" or copy_conflicts:
            print(
                "\nRe-run with --force to overwrite / re-sync, or revert the local "
                "changes and re-run.",
                file=sys.stderr,
            )
        return 1

    # Phase 3: apply. Past this point, no user-recoverable error should abort.
    copy_report = apply_copy_artifacts(target, copy_pending)
    settings_report = apply_merge_settings(settings_plan, args.force)
    claude_status, claude_line = apply_inject_claude_md(claude_plan)
    write_version(target)

    test_result: Optional[Tuple[bool, str]] = None
    if not args.skip_tests:
        test_result = run_tests(target)

    print_summary(
        target, copy_report, settings_report, claude_status, claude_line,
        claude_plan.get("match_count"), test_result,
    )
    return 0


def print_summary(
    target: Path,
    copy_report: List[Tuple[str, str]],
    settings_report: List[Tuple[str, str]],
    claude_status: str,
    claude_line: Optional[int],
    claude_match_count: Optional[int],
    test_result: Optional[Tuple[bool, str]],
) -> None:
    w = 5  # bracket inner width — produces "[  new]", "[ same]", "[ over]".

    print(f"claude-chaperone v{__version__} installed to: {target}")
    print()

    print("Files:")
    for status, rel in copy_report:
        tag = f"[{status:>{w}}]"
        extra = "  (--force)" if status == "over" else ""
        print(f"  {tag} {rel}{extra}")
    print()

    print("settings.json:")
    for status, label in settings_report:
        tag = f"[{status:>{w}}]"
        if status == "skip":
            extra = "  (already present)"
        elif status == "over":
            extra = "  (--force)"
        else:
            extra = ""
        print(f"  {tag} {label}{extra}")
    print()

    print("CLAUDE.md:")
    if claude_status == "add":
        print(f"  [{'add':>{w}}] marker block appended at line {claude_line}")
    elif claude_status == "same":
        print(f"  [{'same':>{w}}] marker block already present and current")
    elif claude_status == "resync":
        print(
            f"  [{'sync':>{w}}] marker block version re-synced at line {claude_line}"
        )
    elif claude_status == "replace-multi":
        n = claude_match_count or 0
        print(
            f"  [{'over':>{w}}] {n} marker blocks consolidated into one at line {claude_line}  (--force)"
        )
    elif claude_status == "replace":
        print(
            f"  [{'over':>{w}}] marker block replaced at line {claude_line}  (--force)"
        )
    print()

    if test_result is not None:
        ok, out = test_result
        print("Post-install test:")
        summary_line = _pick_test_summary(out)
        if summary_line:
            print(f"  {summary_line}")
        elif out:
            print("  " + out.splitlines()[-1])
        else:
            print("  (no output)")
        if not ok:
            print("  WARNING: test_hooks.py exited non-zero. Install is complete but "
                  "something is off with your Python environment.")
            if out:
                print()
                print(out)
        print()

    print("Next:")
    print(f"  Open a fresh Claude Code session in {target}")
    print('  Run: /chaperone "rough idea of what you want to build"')


if __name__ == "__main__":
    sys.exit(main())
