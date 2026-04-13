# Contributing to claude-chaperone

Thanks for your interest. This repo ships configuration that's copied into other projects, so changes have a wide blast radius — keep the bar high.

## Before you open a PR

1. **Run the hook test suite.** `python .claude/hooks/test_hooks.py` — all 22 tests must pass.
2. **Don't break the hook invariants** (see `CLAUDE.md`):
   - Stdlib only. No third-party imports.
   - Python 3.8+ compatible (use `from __future__ import annotations` for type hints).
   - Cross-platform: `pathlib.Path`, not hardcoded separators. `$CLAUDE_PROJECT_DIR` for cwd.
   - Each hook uses the channel Claude Code's spec mandates for its event type. Don't "simplify" by switching channels — output on the wrong channel is silently dropped.
3. **Read the design docs** (`docs/WORKFLOW.md`, `docs/AUTOMATION.md`) before changing behavior in hooks, slash commands, or the skill. Several rules are load-bearing.

## What's in scope

- Fixes to existing hooks, commands, or skill prompts.
- New hooks that extend the workflow without breaking the `plan/current_phase.txt` gate (hooks must no-op when the workflow isn't active).
- Documentation improvements.

## What's out of scope

- Auto-push, auto-clear, or auto-model-switch hooks. These are explicitly un-automatable — see `docs/AUTOMATION.md`.
- Third-party dependencies. The whole point is zero-install.

## Reporting issues

Open a GitHub issue with: your OS, Python version, Claude Code version, and a minimal repro.
