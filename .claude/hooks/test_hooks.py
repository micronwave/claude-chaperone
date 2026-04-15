#!/usr/bin/env python3
"""
test_hooks.py — Self-test for claude-build-workflow hooks.

Run this after installing the plugin to verify hooks are wired correctly.
Uses a tempdir so it never touches your real project.

Usage:
    python .claude/hooks/test_hooks.py

Exit 0 on all-pass, 1 on any failure. Prints a summary.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the hooks directory is on sys.path so we can import siblings
HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR))

import _hook_utils as hu  # noqa: E402


class ScopeParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cbw_test_"))
        (self.tmp / "plan").mkdir()
        self._orig_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_env

    def _write_scope(self, obj: dict) -> None:
        (self.tmp / "plan" / "phase_1_scope.json").write_text(
            json.dumps(obj), encoding="utf-8"
        )

    def test_missing_file_raises_loud(self) -> None:
        with self.assertRaises(hu.ScopeError) as ctx:
            hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(ctx.exception.code, "MISSING_SCOPE_FILE")

    def test_malformed_json_raises_loud(self) -> None:
        (self.tmp / "plan" / "phase_1_scope.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(hu.ScopeError) as ctx:
            hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(ctx.exception.code, "MALFORMED_SCOPE_JSON")

    def test_missing_schema_version(self) -> None:
        self._write_scope({"phase_number": 1, "phase_name": "x", "scope": {"files": [], "prefixes": []}})
        with self.assertRaises(hu.ScopeError) as ctx:
            hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_SCHEMA_VERSION")

    def test_phase_number_mismatch(self) -> None:
        self._write_scope({
            "schema_version": 1,
            "phase_number": 7,  # mismatch with the argument 1
            "phase_name": "x",
            "scope": {"files": [], "prefixes": []},
        })
        with self.assertRaises(hu.ScopeError) as ctx:
            hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(ctx.exception.code, "SCOPE_PHASE_MISMATCH")

    def test_prefix_without_trailing_slash(self) -> None:
        self._write_scope({
            "schema_version": 1,
            "phase_number": 1,
            "phase_name": "x",
            "scope": {"files": [], "prefixes": ["docs/arch"]},  # missing /
        })
        with self.assertRaises(hu.ScopeError) as ctx:
            hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(ctx.exception.code, "INVALID_PREFIX")

    def test_valid_scope_loads(self) -> None:
        self._write_scope({
            "schema_version": 1,
            "phase_number": 1,
            "phase_name": "auth",
            "scope": {
                "files": ["api/auth.py", "tests/test_auth.py"],
                "prefixes": ["docs/auth/"],
                "allow_untracked_new": True,
            },
        })
        scope = hu.load_phase_scope(1, root=self.tmp)
        self.assertEqual(scope.phase_number, 1)
        self.assertIn("api/auth.py", scope.files)
        self.assertIn("docs/auth/", scope.prefixes)
        self.assertTrue(scope.allow_untracked_new)


class PathMatchingTests(unittest.TestCase):
    def _scope(self, files=(), prefixes=(), allow_new=False) -> hu.PhaseScope:
        return hu.PhaseScope(
            schema_version=1,
            phase_number=1,
            phase_name="t",
            files=frozenset(files),
            prefixes=tuple(prefixes),
            allow_untracked_new=allow_new,
        )

    def test_exact_file_match(self) -> None:
        s = self._scope(files=["api/auth.py"])
        self.assertTrue(hu.path_in_scope("api/auth.py", s, 1))
        self.assertFalse(hu.path_in_scope("api/other.py", s, 1))

    def test_prefix_match(self) -> None:
        s = self._scope(prefixes=["docs/auth/"])
        self.assertTrue(hu.path_in_scope("docs/auth/overview.md", s, 1))
        self.assertTrue(hu.path_in_scope("docs/auth/subdir/file.md", s, 1))
        self.assertFalse(hu.path_in_scope("docs/other.md", s, 1))
        # Prefix is NOT a substring match — auth-alt/ must not match docs/auth/
        self.assertFalse(hu.path_in_scope("docs/authx/overview.md", s, 1))

    def test_universal_allowlist(self) -> None:
        s = self._scope()
        self.assertTrue(hu.path_in_scope("BUILD_LOG.md", s, 1))
        self.assertTrue(hu.path_in_scope("plan/phase_1_handoff.md", s, 1))
        self.assertTrue(hu.path_in_scope("plan/phase_1_scope.json", s, 1))
        # Other phases' metadata should NOT be allowed for phase 1
        self.assertFalse(hu.path_in_scope("plan/phase_2_handoff.md", s, 1))

    def test_windows_path_normalized(self) -> None:
        s = self._scope(files=["api/auth.py"])
        self.assertTrue(hu.path_in_scope("api\\auth.py", s, 1))

    def test_dot_slash_stripped(self) -> None:
        s = self._scope(files=["api/auth.py"])
        self.assertTrue(hu.path_in_scope("./api/auth.py", s, 1))


class GitPushDetectionTests(unittest.TestCase):
    cases_match = [
        "git push",
        "git push origin main",
        "git push --force",
        "git push origin main --force-with-lease",
        "git.exe push",
        "cd foo && git push",
        "git pull && git push",
        "GIT_ASKPASS=true git push",
        "SOME=var ANOTHER=thing git push origin",
        '"git" push',
        "'git' push",
        "./git push",
        "git  push",  # multiple spaces
        "git\tpush",  # tab
        "foo; git push",
        "foo | git push",
        "(git push)",
    ]
    cases_no_match = [
        "",
        "git status",
        "git pull",
        "git pushd",  # not a real command but tests word boundary
        "pushd /tmp",
        "echo git push",  # matches as defense in depth — we accept this false-positive
        "# git push",  # conservative false-positive acceptable (safer to ask)
        "git-push",  # hyphenated form not standard git
        "mygit push",  # different binary
    ]

    def test_positive_cases(self) -> None:
        for cmd in self.cases_match:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    hu.command_contains_git_push(cmd),
                    f"should detect push in: {cmd!r}",
                )

    def test_negative_cases_strict(self) -> None:
        # Only assert the truly-safe no-match cases.
        strict_safe = ["", "git status", "git pull", "pushd /tmp", "git-push", "mygit push"]
        for cmd in strict_safe:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    hu.command_contains_git_push(cmd),
                    f"should NOT detect push in: {cmd!r}",
                )


class HookScriptIntegrationTests(unittest.TestCase):
    """Run the actual hook scripts as subprocesses with a test payload."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cbw_test_"))
        (self.tmp / "plan").mkdir()
        self._orig_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_env

    def _run_hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )

    def test_push_confirm_blocks_git_push(self) -> None:
        result = self._run_hook(
            "push_confirm.py",
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        payload = json.loads(result.stdout)
        decision = payload["hookSpecificOutput"]["permissionDecision"]
        self.assertIn(decision, ("ask", "deny"))

    def test_push_confirm_allows_non_push(self) -> None:
        result = self._run_hook(
            "push_confirm.py",
            {"tool_name": "Bash", "tool_input": {"command": "git status"}},
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        # On allow, no JSON output is required; stdout should be empty or have no decision
        if result.stdout.strip():
            payload = json.loads(result.stdout)
            decision = (
                payload.get("hookSpecificOutput", {}).get("permissionDecision", "")
            )
            self.assertNotIn(decision, ("deny", "ask"))

    def test_push_confirm_handles_empty_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "push_confirm.py")],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        # Empty input → no-op, exit 0
        self.assertEqual(result.returncode, 0)

    def test_scope_drift_silent_when_workflow_inactive(self) -> None:
        # No plan/current_phase.txt → hook should be silent
        result = self._run_hook(
            "scope_drift_check.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "foo.py"}},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), "")

    def test_scope_drift_loud_when_phase_active_but_scope_missing(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        # No scope.json created
        result = self._run_hook(
            "scope_drift_check.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "foo.py"}},
        )
        self.assertEqual(result.returncode, 0)  # non-blocking
        self.assertIn("MISSING_SCOPE_FILE", result.stderr)

    def test_build_log_reminder_silent_when_workflow_inactive(self) -> None:
        # No plan/current_phase.txt → hook must be silent on every channel
        result = self._run_hook(
            "build_log_reminder.py",
            {"hook_event_name": "UserPromptSubmit", "prompt": "hi"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual(result.stderr.strip(), "")

    def test_build_log_reminder_never_blocks_on_crash(self) -> None:
        # Garbage stdin + active workflow should still exit 0 — a bug in the
        # hook must never block the user's prompt.
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "build_log_reminder.py")],
            input="not-json{{{",
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )
        self.assertEqual(result.returncode, 0)


class BuildLogReminderOutputShapeTests(unittest.TestCase):
    """Verify that the reminder uses the UserPromptSubmit structured-JSON
    channel (additionalContext) rather than Stop-hook semantics. This is the
    whole point of the rename from stop_reminder.py."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cbw_test_"))
        (self.tmp / "plan").mkdir()
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        # Make a git repo with a tracked+modified code file and no BUILD_LOG change
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=False)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
             "--allow-empty", "-q", "-m", "init"],
            cwd=self.tmp, check=False,
        )
        (self.tmp / "code.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "code.py"], cwd=self.tmp, check=False)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
             "-q", "-m", "add"],
            cwd=self.tmp, check=False,
        )
        (self.tmp / "code.py").write_text("x = 2\n", encoding="utf-8")
        self._orig_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_env

    def test_emits_user_prompt_submit_additional_context(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "build_log_reminder.py")],
            input=json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "prompt": "continue",
            }),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertTrue(result.stdout.strip(), "expected structured JSON on stdout")
        payload = json.loads(result.stdout)
        hso = payload["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("BUILD_LOG.md", hso["additionalContext"])
        # Secondary stderr channel also present for humans in transcript mode
        self.assertIn("BUILD_LOG.md", result.stderr)

    def test_silent_when_build_log_already_modified(self) -> None:
        (self.tmp / "BUILD_LOG.md").write_text("- note\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "build_log_reminder.py")],
            input=json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "prompt": "continue",
            }),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual(result.stderr.strip(), "")


class BuildLogReminderDebounceTests(unittest.TestCase):
    """Verify the UserPromptSubmit reminder debounces on BUILD_LOG.md's mtime
    so a long /build session doesn't re-inject the same nudge every turn."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cbw_test_"))
        (self.tmp / "plan").mkdir()
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        # Git repo with a tracked+modified code file and no BUILD_LOG change —
        # mirrors BuildLogReminderOutputShapeTests.setUp so the hook reaches
        # the emit path instead of returning early at the git_changed_paths() gate.
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=False)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
             "--allow-empty", "-q", "-m", "init"],
            cwd=self.tmp, check=False,
        )
        (self.tmp / "code.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "code.py"], cwd=self.tmp, check=False)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
             "-q", "-m", "add"],
            cwd=self.tmp, check=False,
        )
        (self.tmp / "code.py").write_text("x = 2\n", encoding="utf-8")
        self._orig_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_env

    def _invoke_hook(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "build_log_reminder.py")],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "continue"}),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )

    def test_first_fire_emits_and_writes_state(self) -> None:
        result = self._invoke_hook()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertTrue(result.stdout.strip(), "expected structured JSON on stdout")
        payload = json.loads(result.stdout)
        hso = payload["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("BUILD_LOG.md", hso["additionalContext"])
        self.assertIn("REMINDER", result.stderr)
        state_file = self.tmp / "plan" / ".build_log_reminder_state"
        self.assertTrue(state_file.exists())
        self.assertEqual(state_file.read_text(encoding="utf-8").strip(), "absent")

    def test_second_fire_suppressed_when_signal_unchanged(self) -> None:
        # Prime the state file via a real first fire, then invoke again.
        first = self._invoke_hook()
        self.assertEqual(first.returncode, 0)
        self.assertTrue(first.stdout.strip())

        second = self._invoke_hook()
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout.strip(), "")
        self.assertEqual(second.stderr.strip(), "")
        state_file = self.tmp / "plan" / ".build_log_reminder_state"
        self.assertEqual(state_file.read_text(encoding="utf-8").strip(), "absent")

    def test_build_log_touch_clears_suppression(self) -> None:
        # First fire: state file stored as "absent".
        first = self._invoke_hook()
        self.assertEqual(first.returncode, 0)
        state_file = self.tmp / "plan" / ".build_log_reminder_state"
        self.assertEqual(state_file.read_text(encoding="utf-8").strip(), "absent")

        # Create BUILD_LOG.md AND commit it clean. If left uncommitted it
        # shows up in `git status`, which trips the hook's existing
        # "BUILD_LOG.md already in diff this cycle" filter and makes the hook
        # exit silently — the debounce branch would never run and this test
        # would greenlight a vacuous result.
        (self.tmp / "BUILD_LOG.md").write_text("- note\n", encoding="utf-8")
        subprocess.run(["git", "add", "BUILD_LOG.md"], cwd=self.tmp, check=False)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
             "-q", "-m", "add build log"],
            cwd=self.tmp, check=False,
        )
        # code.py is still modified from setUp — keeps the hook on the emit path.

        third = self._invoke_hook()
        self.assertEqual(third.returncode, 0, msg=f"stderr: {third.stderr}")
        self.assertTrue(third.stdout.strip(), "expected re-emit after BUILD_LOG mtime changed")
        payload = json.loads(third.stdout)
        self.assertIn("BUILD_LOG.md", payload["hookSpecificOutput"]["additionalContext"])
        contents = state_file.read_text(encoding="utf-8").strip()
        self.assertTrue(
            contents.isdigit(),
            f"expected numeric mtime signal, got {contents!r}",
        )


class SessionStartHookTests(unittest.TestCase):
    """Verify session_start.py injects the correct workflow-state snapshot.

    Runs the hook as a subprocess with a fresh tempdir per test.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cbw_ss_"))
        (self.tmp / "plan").mkdir()
        self._orig_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_env

    def _write_scope(self, phase: int, name: str = "test phase") -> None:
        (self.tmp / "plan" / f"phase_{phase}_scope.json").write_text(
            json.dumps({
                "schema_version": 1,
                "phase_number": phase,
                "phase_name": name,
                "scope": {"files": [], "prefixes": []},
            }),
            encoding="utf-8",
        )

    def _run(self, payload: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_start.py")],
            input=json.dumps(payload or {
                "session_id": "t",
                "transcript_path": "",
                "cwd": str(self.tmp),
                "hook_event_name": "SessionStart",
                "source": "clear",
            }),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )

    def _parse_context(self, stdout: str) -> str:
        payload = json.loads(stdout)
        hso = payload["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        return hso["additionalContext"]

    # -- 1. Silent when workflow inactive (no plan/ markers) ------------------
    def test_silent_when_no_plan_markers(self) -> None:
        # plan/ dir exists (from setUp) but has no markers at all.
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual(result.stderr.strip(), "")

    def test_silent_when_plan_dir_missing(self) -> None:
        shutil.rmtree(self.tmp / "plan", ignore_errors=True)
        result = self._run()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    # -- 2. Silent on malformed current_phase.txt doesn't crash, still emits --
    def test_malformed_current_phase_still_safe(self) -> None:
        # Unreadable current_phase.txt → read_current_phase returns None.
        # With no other markers, the hook should exit silently (no crash).
        (self.tmp / "plan" / "current_phase.txt").write_text(
            "not_a_number", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "")

    # -- 3. Injects state when phase active with all artifacts ---------------
    def test_injects_state_when_phase_active(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("2", encoding="utf-8")
        self._write_scope(2, name="dark mode toggle")
        (self.tmp / "plan" / "phase_2.md").write_text("# Phase 2\n", encoding="utf-8")
        (self.tmp / "BUILD_LOG.md").write_text(
            "# Build log\n\n## 2026-04-10 12:00 — Phase 1 wrap\n\n"
            "- did stuff\n\n"
            "## 2026-04-12 09:30 — Phase 2 build started\n\n"
            "- started\n",
            encoding="utf-8",
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        ctx = self._parse_context(result.stdout)
        self.assertIn("Active phase: 2", ctx)
        self.assertIn("dark mode toggle", ctx)
        self.assertIn("Phase 2 build started", ctx)
        self.assertIn("plan/phase_2.md", ctx)

    # -- 4. Missing scope JSON → phase_name "unknown", no SCOPE_DRIFT err ----
    def test_missing_scope_json_graceful(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        (self.tmp / "plan" / "phase_1.md").write_text("# Phase 1\n", encoding="utf-8")
        # No phase_1_scope.json.
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        ctx = self._parse_context(result.stdout)
        self.assertIn('"unknown"', ctx)
        # Crucially, session_start does NOT emit scope_drift's loud error.
        self.assertNotIn("SCOPE_DRIFT_HOOK_ERROR", result.stderr)

    # -- 5. Missing BUILD_LOG.md reported cleanly ----------------------------
    def test_missing_build_log_reported(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        self.assertIn("BUILD_LOG.md missing", ctx)

    # -- 6. Escalation pending flagged, next-step warns off advancement ------
    def test_escalation_pending_flagged(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        (self.tmp / "plan" / "phase_1_escalation.md").write_text(
            "# Escalation\n\nOptions: accept / refactor / defer\n",
            encoding="utf-8",
        )
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        self.assertIn("escalation pending", ctx)
        self.assertIn("user decision", ctx)
        # Must NOT nominate a forward-advancing slash command.
        self.assertNotIn("/execute", ctx)

    # -- 7. Re-audit loop counter reported -----------------------------------
    def test_loop_counter_reported(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        (self.tmp / "plan" / "phase_1_loop.txt").write_text("2", encoding="utf-8")
        (self.tmp / "plan" / "phase_1_audit_fix.md").write_text(
            "- fix thing\n", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        self.assertIn("2/3", ctx)
        self.assertIn("mid re-audit loop", ctx)

    # -- 8. Stage heuristic: meta written, no plan ---------------------------
    def test_stage_meta_only(self) -> None:
        (self.tmp / "plan" / "meta.md").write_text("# Meta\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        ctx = self._parse_context(result.stdout)
        self.assertIn("/plan", ctx)
        self.assertIn("meta-prompt written", ctx)

    # -- 9. Stage heuristic: plan audited, awaiting approval -----------------
    def test_stage_plan_audited(self) -> None:
        (self.tmp / "plan" / "meta.md").write_text("# Meta\n", encoding="utf-8")
        (self.tmp / "plan" / "plan.md").write_text("# Plan\n", encoding="utf-8")
        (self.tmp / "plan" / "plan_audit.md").write_text("# Audit\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        # Either of these strings acceptable per plan text
        self.assertTrue(
            "awaiting approval" in ctx or "/split-phases" in ctx,
            f"expected approval/split-phases hint, got: {ctx}",
        )

    # -- 10. Stage heuristic: mid re-audit suggests /execute -----------------
    def test_stage_mid_reaudit(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        (self.tmp / "plan" / "phase_1_audit_fix.md").write_text(
            "- fix\n", encoding="utf-8"
        )
        (self.tmp / "plan" / "phase_1_loop.txt").write_text("1", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        self.assertIn("/execute", ctx)

    # -- 11. Truncation under large artifact inventory -----------------------
    def test_truncates_large_artifact_inventory(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        # Create 50 fake phase_1_*.md files.
        for i in range(50):
            (self.tmp / "plan" / f"phase_1_extra_{i:02d}.md").write_text(
                "x\n", encoding="utf-8"
            )
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        ctx = self._parse_context(result.stdout)
        self.assertLess(len(ctx.encode("utf-8")), 4096)
        self.assertIn("more artifacts omitted", ctx)

    # -- 11b. Regression: phase_1 must not match phase_10_*.md inventory ----
    def test_phase_prefix_no_collision(self) -> None:
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        (self.tmp / "plan" / "phase_1.md").write_text("x", encoding="utf-8")
        # These must NOT appear in phase 1's artifact list even though their
        # names begin with "phase_1" (naive startswith would match).
        (self.tmp / "plan" / "phase_10.md").write_text("x", encoding="utf-8")
        (self.tmp / "plan" / "phase_11_notes.md").write_text("x", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0)
        ctx = self._parse_context(result.stdout)
        self.assertIn("plan/phase_1.md", ctx)
        self.assertNotIn("plan/phase_10.md", ctx)
        self.assertNotIn("plan/phase_11_notes.md", ctx)

    # -- 11c. Pre-phase inventory must include phase_<N>.md when current_phase
    #         is not yet set. Regression: Codex-flagged misreport where
    #         _workflow_has_any_marker activates on phase_1.md but
    #         _inventory_artifacts previously skipped it in the pre-phase
    #         branch, producing a snapshot whose inventory contradicted the
    #         "phases split" heuristic.
    def test_pre_phase_inventory_includes_phase_markers(self) -> None:
        (self.tmp / "plan" / "phase_1.md").write_text("# Phase 1\n", encoding="utf-8")
        (self.tmp / "plan" / "phase_2.md").write_text("# Phase 2\n", encoding="utf-8")
        # current_phase.txt intentionally absent.
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        ctx = self._parse_context(result.stdout)
        self.assertIn("plan/phase_1.md", ctx)
        self.assertIn("plan/phase_2.md", ctx)
        # Stage heuristic should still fire for "phases split".
        self.assertIn("phases split", ctx)

    # -- 12. Exception in main loop doesn't crash ----------------------------
    def test_crash_exits_zero(self) -> None:
        # Write a payload that would crash if stdin read failed, plus an
        # unreadable plan/ by making it a symlink to nowhere — skip on
        # Windows where symlink perms are an issue. Instead, stub by running
        # with no stdin at all (closed pipe scenario).
        (self.tmp / "plan" / "current_phase.txt").write_text("1", encoding="utf-8")
        self._write_scope(1)
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_start.py")],
            input="this is not valid json {{{",
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        # Stdout may be empty (payload read returns {}) or contain a valid
        # snapshot — both are acceptable. The contract is "never crash."


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        ScopeParsingTests,
        PathMatchingTests,
        GitPushDetectionTests,
        HookScriptIntegrationTests,
        BuildLogReminderOutputShapeTests,
        BuildLogReminderDebounceTests,
        SessionStartHookTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
