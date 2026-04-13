# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`claude-chaperone` is a **distributable meta-workflow** for Claude Code, not a consumer application. The artifacts in this repo (`.claude/` directory, `settings.json`, `CLAUDE.md.snippet`) are designed to be copied into *other* projects to enforce a structured build workflow. Keep that audience in mind: changes here ship as configuration to downstream users.

`CLAUDE.md.snippet` is NOT this project's CLAUDE.md — it's the text downstream users paste into their own CLAUDE.md after installing the workflow.

## Commands

- **Run the hook test suite:** `python .claude/hooks/test_hooks.py` — 22 unit + integration tests. Must be green before shipping any hook change. There is no other test suite, build step, or lint command in this repo.
- **Smoke-test hooks end-to-end:** see the fixture recipe in `.claude/hooks/README.md` (create `plan/current_phase.txt` + `plan/phase_1_scope.json`, trigger each hook).

## Architecture

Three cooperating layers. Understanding how they interact is essential before editing any one of them.

1. **Slash commands** (`.claude/commands/*.md`) — twelve workflow stages: `/meta-prompt` → `/plan` → `/plan-audit` → `/split-phases` → `/phase-audit` → `/build` → `/build-audit` → `/execute` → `/re-audit` → `/test` → `/wrap` + `/handoff`. Each is a single-purpose prompt executed in an intentionally fresh context. The user is expected to `/clear` between stages — this is the #1 quality mechanism in the workflow and must not be "optimized away."

2. **Hooks** (`.claude/hooks/*.py`, registered in `settings.json`) — cross-platform Python 3.8+, **stdlib only**, no third-party dependencies. Three active hooks:
   - `scope_drift_check.py` (PostToolUse Edit/Write/NotebookEdit) → stderr warning when edits leave the declared phase scope.
   - `push_confirm.py` (PreToolUse Bash) → structured JSON forcing a permission prompt on `git push`.
   - `build_log_reminder.py` (UserPromptSubmit) → structured `additionalContext` JSON injecting a reminder when code changes outlast `BUILD_LOG.md`.

   All hooks gate on `plan/current_phase.txt` — if the pointer is missing, they exit silently. This means the plugin imposes zero friction on projects where the workflow isn't active.

3. **Skill** (`.claude/skills/full-build-workflow/`) — `SKILL.md` orchestrates the whole sequence and auto-triggers on keywords ("new feature", "build phase", "audit", "handoff", "wrap up"). `references/templates/` and `references/prompts/` contain the reusable artifacts the commands emit or consume (`plan.md`, `handoff.md`, `audit_fix.md`, `build_log.md`, `phase_scope.json`, `SCOPE_SCHEMA.md`).

## Non-negotiable design invariants

These are load-bearing — violating any of them breaks a documented guarantee in `docs/WORKFLOW.md` or `docs/AUTOMATION.md`. Read those docs before changing behavior in these areas.

- **Each hook uses the channel Claude Code spec mandates for its event type.** PreToolUse → structured JSON with `permissionDecision`. PostToolUse → stderr + exit 0. UserPromptSubmit → structured `additionalContext` JSON (the only channel that reaches Claude, not just the terminal). Do NOT "simplify" by switching to stdout/stderr uniformly — output on the wrong channel is silently dropped.
- **`scope_drift_check.py` fails LOUDLY on missing/malformed scope JSON**, never silently passes. A silently-broken guard is worse than no guard.
- **`build_log_reminder.py` must stay on UserPromptSubmit, not Stop.** Stop-hook stdout does not reach Claude's conversation per spec.
- **Hooks are non-blocking** — they emit warnings but exit 0 so edits/commands proceed. Post-hoc revert beats a blocked-edit fight.
- **Never add a hook that auto-pushes, auto-clears, or auto-switches models.** These are explicitly un-automatable per `docs/AUTOMATION.md`; the workarounds there are the contract.
- **Re-audit loops cap at 3 iterations** before escalation to the user. Documented exit condition — don't remove.

## Shell environment note

This repo develops on Windows with a bash shell. Use Unix shell syntax in scripts and commands (forward slashes, `/dev/null`, not `NUL`). Hook scripts themselves are invoked via `python "$CLAUDE_PROJECT_DIR"/...` for cross-platform portability.
