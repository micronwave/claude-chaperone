# Changelog

All notable changes to `claude-chaperone` will be documented here.

## v0 — initial release

- 12 slash commands covering the full flow: `/meta-prompt` → `/plan` → `/plan-audit` → `/split-phases` → `/phase-audit` → `/build` → `/build-audit` → `/execute` → `/re-audit` → `/test` → `/wrap` + `/handoff`.
- 3 hooks (stdlib-only Python 3.8+, cross-platform): `scope_drift_check.py`, `push_confirm.py`, `build_log_reminder.py`.
- 1 skill (`full-build-workflow`) that auto-triggers the sequence on keywords.
- Documentation: `docs/WORKFLOW.md`, `docs/AUTOMATION.md`, `docs/SECOND_OPINION.md`.
- 22-test suite in `.claude/hooks/test_hooks.py`.
