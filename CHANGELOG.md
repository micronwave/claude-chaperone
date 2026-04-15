# Changelog

All notable changes to `claude-chaperone` will be documented here.

## Unreleased

- Add `session_start.py` (SessionStart hook): injects a workflow-state snapshot (current phase, last BUILD_LOG entry, plan/ artifact inventory, re-audit loop counter, escalation flag, suggested next slash command) after `/clear` / resume / new session — so Claude picks up without the user re-briefing.
- Fix: `session_start.py` pre-phase inventory now includes `phase_<N>.md` files when `current_phase.txt` is not yet set. Previously the hook would emit a "phases split" snapshot whose inventory contradicted the heuristic by omitting the `phase_N.md` marker that triggered activation.
- Debounce `build_log_reminder` so repeat prompts don't re-inject the same nudge.
- Add exception guard to `scope_drift_check` to match the non-blocking pattern of other hooks.
- Thin `build.md` to orchestration; behavioral rules live in `build-prompt.md`.
- Test suite: 22 → 40.

## v0 — initial release

- 12 slash commands covering the full flow: `/meta-prompt` → `/plan` → `/plan-audit` → `/split-phases` → `/phase-audit` → `/build` → `/build-audit` → `/execute` → `/re-audit` → `/test` → `/wrap` + `/handoff`.
- 3 hooks (stdlib-only Python 3.8+, cross-platform): `scope_drift_check.py`, `push_confirm.py`, `build_log_reminder.py`.
- 1 skill (`full-build-workflow`) that auto-triggers the sequence on keywords.
- Documentation: `docs/WORKFLOW.md`, `docs/AUTOMATION.md`, `docs/SECOND_OPINION.md`.
- 22-test suite in `.claude/hooks/test_hooks.py`.
