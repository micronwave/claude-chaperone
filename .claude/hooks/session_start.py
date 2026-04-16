#!/usr/bin/env python3
"""
session_start.py — SessionStart hook.

When a Claude Code session begins (new session, resume, or after /clear), and
the chaperone workflow is active, inject a factual state snapshot into
Claude's conversation via the structured `additionalContext` JSON channel.

Why SessionStart?
    Per the Claude Code hook spec, SessionStart fires on all three of:
    new session, resume, and post-/clear. Its stdout reaches Claude's
    conversation context (same channel as UserPromptSubmit). A UserPromptSubmit
    hook would double-fire on every turn; SessionStart is the unique trigger
    that maps to "Claude needs to re-orient."

What this hook does:
    - If plan/ has no workflow markers, exits silently (workflow off).
    - If current_phase.txt exists, builds a per-phase snapshot.
    - Otherwise (pre-phase stages: meta/plan/plan-audit/split drafted but
      current_phase.txt not yet set), builds a pre-phase snapshot.
    - Best-effort loads phase scope JSON (for phase_name only).
    - Best-effort tails BUILD_LOG.md for the last `## ` header.
    - Inventories plan/phase_<N>_* artifacts + universal plan files.
    - Detects re-audit loop counter and escalation state.
    - Computes a conservative "stage heuristic" string.
    - Emits a single JSON line on stdout and exits 0.

What this hook does NOT do:
    - Does not modify any file.
    - Does not run slash commands or call git commands other than those
      already wrapped by `_hook_utils.git_changed_paths`.
    - Does not emit stderr (the snapshot is for Claude, not the human).
    - Does not raise SCOPE_DRIFT_HOOK_ERROR on malformed scope JSON — that's
      scope_drift_check's job; double-emitting would be noise.

Non-blocking: any exception is caught at __main__ and maps to exit 0. A
broken session-start hook must never prevent a session from starting.
"""
from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import _hook_utils as hu  # noqa: E402


MAX_ARTIFACTS_LISTED = 8
MAX_HEADER_CHARS = 160
BUILD_LOG_TAIL_BYTES = 4096

_PRE_PHASE_MARKERS = ("meta.md", "plan.md", "plan_audit.md", "phase_1.md")


def _read_phase_name(phase: int, root: Path) -> str:
    try:
        scope = hu.load_phase_scope(phase, root=root)
    except hu.ScopeError:
        return "unknown"
    except Exception:
        return "unknown"
    return scope.phase_name or "unknown"


def _tail_last_header(build_log: Path) -> str | None:
    """Return the last `## ` header line (without the '## ' prefix), or None.

    Tails up to ~4 KB so a giant BUILD_LOG doesn't balloon the hook's cost.
    """
    try:
        size = build_log.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    try:
        with build_log.open("rb") as fh:
            if size > BUILD_LOG_TAIL_BYTES:
                fh.seek(-BUILD_LOG_TAIL_BYTES, 2)
                # Skip the (potentially partial) first line after the seek.
                fh.readline()
            data = fh.read()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    last = None
    for line in text.splitlines():
        if line.startswith("## "):
            last = line[3:].strip()
    if last is None:
        return None
    if len(last) > MAX_HEADER_CHARS:
        last = last[:MAX_HEADER_CHARS].rstrip() + "…"
    return last


def _read_loop_counter(phase: int, root: Path) -> tuple[bool, str]:
    """Return (loop_file_present, human_readable_value).

    value is "M/3" when parseable, "?/3" otherwise.
    """
    p = root / "plan" / f"phase_{phase}_loop.txt"
    if not p.exists():
        return (False, "")
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return (True, "?/3")
    try:
        n = int(raw)
        return (True, f"{n}/3")
    except ValueError:
        return (True, "?/3")


def _name_is_phase_artifact(name: str, phase: int | None) -> bool:
    """True iff ``name`` is a ``plan/phase_<N>(.|_)...`` file with a tracked
    extension. When ``phase`` is None, any phase number matches; otherwise
    the digit run after ``phase_`` must equal ``phase`` exactly (so phase 1
    does not match ``phase_10.md``).
    """
    if not name.endswith((".md", ".json", ".txt")):
        return False
    if not name.startswith("phase_"):
        return False
    i = len("phase_")
    start = i
    while i < len(name) and name[i].isdigit():
        i += 1
    if i == start:
        return False
    if i >= len(name) or name[i] not in (".", "_"):
        return False
    if phase is None:
        return True
    try:
        return int(name[start:i]) == phase
    except ValueError:
        return False


def _inventory_artifacts(phase: int | None, root: Path) -> list[tuple[str, float]]:
    """Return [(relpath, mtime), ...] sorted by mtime desc for display.

    Includes the universal workflow files (meta.md, plan.md, plan_audit.md).
    When ``phase`` is set, additionally includes files for that phase only.
    When ``phase`` is None (pre-phase state: split done but current_phase.txt
    not yet set), includes files for any phase — otherwise a phase_1.md-only
    activation would emit a snapshot whose inventory omits the very marker
    that triggered it.
    """
    plan = root / "plan"
    if not plan.is_dir():
        return []
    wanted: list[Path] = []
    for name in ("meta.md", "plan.md", "plan_audit.md"):
        fp = plan / name
        if fp.exists():
            wanted.append(fp)
    try:
        for child in plan.iterdir():
            if not child.is_file():
                continue
            if _name_is_phase_artifact(child.name, phase):
                wanted.append(child)
    except OSError:
        pass
    results: list[tuple[str, float]] = []
    for fp in wanted:
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            continue
        results.append((f"plan/{fp.name}", mtime))
    results.sort(key=lambda r: r[1], reverse=True)
    return results


def _stage_heuristic(phase: int | None, root: Path) -> str:
    """Conservative one-line description of the workflow's current stage."""
    plan = root / "plan"
    exists = lambda name: (plan / name).exists()  # noqa: E731

    if phase is None:
        # Pre-phase branches: current_phase.txt not yet set but plan artifacts
        # on disk. Order matters — check the latest artifact first.
        if exists("phase_1.md"):
            return "phases split, run /phase-audit then set plan/current_phase.txt to 1"
        if exists("plan_audit.md"):
            return "plan audited, awaiting approval — then /split-phases"
        if exists("plan.md"):
            return "plan written, run /plan-audit next"
        if exists("meta.md"):
            return "meta-prompt written, awaiting /plan (ambiguities may need resolution first)"
        return "unknown — read plan/ directory to orient"

    # Active-phase branches (current_phase.txt exists with a valid integer).
    if exists(f"phase_{phase}_escalation.md"):
        return "escalation pending — user decision required"

    loop_present, loop_val = _read_loop_counter(phase, root)
    if loop_present:
        return f"mid re-audit loop ({loop_val})"

    if exists(f"phase_{phase}_audit_fix.md"):
        return "audit complete, run /execute"

    if exists(f"phase_{phase}_handoff.md"):
        return "phase wrapped, next phase set up"

    if exists(f"phase_{phase}.md"):
        return f"mid-build for phase {phase}"

    return "unknown — read plan/ directory to orient"


def _suggested_next(stage: str) -> str:
    if stage == "escalation pending — user decision required":
        return (
            "Awaiting user decision on escalation. Do NOT advance the workflow — "
            "read plan/phase_<N>_escalation.md and wait for the user's call."
        )
    if stage == "audit complete, run /execute":
        return "Next likely command: /execute. Confirm with the user before running."
    if stage == "phase wrapped, next phase set up":
        return (
            "Phase wrapped. Next likely command: /clear, then /build on the next phase. "
            "Confirm with the user before running."
        )
    if stage.startswith("meta-prompt written"):
        return (
            "Next likely command: /plan (after ambiguities resolved). "
            "Confirm with the user before running."
        )
    if stage == "plan written, run /plan-audit next":
        return "Next likely command: /plan-audit. Confirm with the user before running."
    if stage.startswith("plan audited"):
        return (
            "Plan audit present — awaiting user approval. Next likely command: /split-phases. "
            "Confirm with the user before running."
        )
    if stage.startswith("phases split"):
        return "Next likely command: /phase-audit. Confirm with the user before running."
    if stage.startswith("mid re-audit loop"):
        return "Next likely command: /execute (to apply audit_fix.md). Confirm with the user before running."
    if stage.startswith("mid-build for phase"):
        return "Next likely command: /build-audit. Confirm with the user before running."
    return "Next likely command: (none — orient by reading plan/ directory). Confirm with the user before running."


def _format_snapshot(
    phase: int | None,
    phase_name: str,
    last_log_header: str | None,
    build_log_state: str,
    artifacts: list[tuple[str, float]],
    loop_present: bool,
    loop_val: str,
    escalation: bool,
    git_changed_count: int,
    stage: str,
    next_step: str,
) -> str:
    import datetime as _dt

    lines: list[str] = ["CHAPERONE STATE (injected by session_start hook):"]
    if phase is None:
        lines.append('- Active phase: none (current_phase.txt not set)')
    else:
        lines.append(f'- Active phase: {phase}: "{phase_name}"')

    if build_log_state == "present" and last_log_header is not None:
        lines.append(f"- Last BUILD_LOG entry: {last_log_header}")
    elif build_log_state == "empty":
        lines.append("- Last BUILD_LOG entry: BUILD_LOG.md empty")
    elif build_log_state == "no-headers":
        lines.append("- Last BUILD_LOG entry: BUILD_LOG.md has no '## ' entries yet")
    else:
        lines.append("- Last BUILD_LOG entry: BUILD_LOG.md missing")

    truncated = False
    listed = artifacts
    if len(listed) > MAX_ARTIFACTS_LISTED:
        listed = artifacts[:MAX_ARTIFACTS_LISTED]
        truncated = True

    if listed:
        lines.append("- Phase artifacts on disk (newest first):")
        for rel, mtime in listed:
            try:
                when = _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            except (OSError, OverflowError, ValueError):
                when = "?"
            marker = "  [ATTENTION]" if rel.endswith("_escalation.md") else ""
            lines.append(f"  - {rel}  ({when}){marker}")
        if truncated:
            lines.append(
                f"  ... ({len(artifacts) - MAX_ARTIFACTS_LISTED} more artifacts omitted)"
            )
    else:
        lines.append("- Phase artifacts on disk: none")

    if loop_present:
        lines.append(f"- Re-audit loop: {loop_val}")

    if escalation:
        lines.append("- Escalation file present — user decision required before advancing")

    lines.append(f"- Uncommitted git changes: {git_changed_count} files")
    lines.append(f"- Workflow stage (heuristic): {stage}")
    lines.append("")
    lines.append(f"Suggested next step: {next_step}")
    lines.append(
        "Do not re-derive state from conversation; read the phase spec and "
        "audit_fix/handoff files listed above."
    )
    return "\n".join(lines)


def _workflow_has_any_marker(phase: int | None, root: Path) -> bool:
    """Decide whether to emit at all.

    Emit when current_phase.txt is set OR any pre-phase plan/ marker exists.
    If neither — the plugin is just sitting dormant in the repo.

    After a completed workflow, ``plan/workflow_complete.txt`` exists and
    ``current_phase.txt`` does not.  In that state the hook stays silent so
    leftover plan artifacts don't keep injecting a stale snapshot.
    ``/meta-prompt`` deletes the marker when a new workflow begins.
    """
    if phase is not None:
        return True
    plan = root / "plan"
    if not plan.is_dir():
        return False
    if (plan / "workflow_complete.txt").exists():
        return False
    return any((plan / name).exists() for name in _PRE_PHASE_MARKERS)


def main() -> int:
    # Consume stdin to avoid blocking the parent. Payload contents unused —
    # we derive state from the filesystem.
    hu.read_hook_payload()

    root = hu.project_root()
    phase = hu.read_current_phase(root=root)

    if not _workflow_has_any_marker(phase, root):
        return 0  # workflow inactive — no snapshot to inject

    if phase is not None:
        phase_name = _read_phase_name(phase, root)
    else:
        phase_name = ""

    build_log = root / "BUILD_LOG.md"
    if not build_log.exists():
        last_header: str | None = None
        build_log_state = "missing"
    else:
        try:
            size = build_log.stat().st_size
        except OSError:
            size = 0
        if size == 0:
            last_header = None
            build_log_state = "empty"
        else:
            last_header = _tail_last_header(build_log)
            build_log_state = "present" if last_header is not None else "no-headers"

    artifacts = _inventory_artifacts(phase, root)
    loop_present, loop_val = (False, "")
    escalation = False
    if phase is not None:
        loop_present, loop_val = _read_loop_counter(phase, root)
        escalation = (root / "plan" / f"phase_{phase}_escalation.md").exists()

    entries = hu.git_changed_paths(root=root)
    git_changed_count = len(entries)

    stage = _stage_heuristic(phase, root)
    next_step = _suggested_next(stage)

    snapshot = _format_snapshot(
        phase=phase,
        phase_name=phase_name,
        last_log_header=last_header,
        build_log_state=build_log_state,
        artifacts=artifacts,
        loop_present=loop_present,
        loop_val=loop_val,
        escalation=escalation,
        git_changed_count=git_changed_count,
        stage=stage,
        next_step=next_step,
    )

    hu.emit_session_start_context(snapshot)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never block a session start because of a hook bug.
        sys.exit(0)
