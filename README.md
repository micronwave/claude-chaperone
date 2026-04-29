# claude-chaperone

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE) ![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue) ![Status](https://img.shields.io/badge/status-v1.1%20chaperone-orange)

> A structured workflow for Claude Code sessions, optimized for output quality over token count.

A one-line install (`curl | python`) that drops a structured build flow into any Claude Code project: plan first, split into phases, test, audit its own diff, commit, move on. Twelve slash commands, four Python hooks (stdlib only, no install), one skill that ties them together.

**You** make the architecture calls, approve the plan, `/clear` between stages.
**Claude** does the mechanical work, test-first, inside a declared scope, with the diff audited before you see it.

---

## Quick start

One-line install into your project:

```bash
curl -sSL https://raw.githubusercontent.com/micronwave/claude-chaperone/main/install.py | python - --target .
```

Or from a clone:

```bash
git clone https://github.com/micronwave/claude-chaperone.git
python claude-chaperone/install.py --target /path/to/your-project
```

The installer merges `settings.json` without clobbering existing hooks, appends a marker block to `CLAUDE.md`, copies commands / hooks / skill files, and runs the 58-test hook suite to verify. Idempotent — safe to re-run (validates existing installs without clobbering). Use `--force` to overwrite divergent chaperone-owned files when upgrading.

Then, in a fresh Claude Code session inside your project:

```
/chaperone "rough idea of what you want to build"
```

`/chaperone` is the single memorable entry point. With an idea it launches the workflow; without arguments it reports where you are and what to run next.

<details>
<summary><b>Manual install (fallback)</b></summary>

<br>

If you want to see exactly what the installer does, or it fails on your system:

```bash
# 1. Clone
git clone https://github.com/micronwave/claude-chaperone.git

# 2. Copy the .claude/ folder into your project (merge if one already exists)
cp -r claude-chaperone/.claude your-project/

# 3. Merge settings.json. If you don't have one:
cp claude-chaperone/settings.json your-project/.claude/settings.json
# If you do, append each entry under its hookEventName array — don't
# replace the whole hooks object, or you'll clobber your existing hooks.

# 4. Paste CLAUDE.md.snippet into your project's CLAUDE.md

# 5. Verify hooks (58 tests, stdlib only)
cd your-project && python .claude/hooks/test_hooks.py
```

</details>

---

## What's in it

**Twelve slash commands**, one per stage. You `/clear` between them so each runs in a fresh context *(plus an optional `/chaperone` entry-point router — not shown)*:

```
/meta-prompt  →  /plan  →  /plan-audit  →  /split-phases  →  /phase-audit
                                                                   ↓
             /wrap  ←  /test  ←  /re-audit  ←  /execute  ←  /build-audit  ←  /build
```

**Four hooks**, Python stdlib:

- `scope_drift_check.py` warns at end of turn if edits left the phase scope
- `push_confirm.py` forces a permission prompt on `git push`
- `build_log_reminder.py` nags when code changes have outrun `BUILD_LOG.md`
- `session_start.py` injects the current workflow state after `/clear` so Claude picks up where you left off

**One skill** that auto-triggers the whole sequence on phrases like "new feature", "build phase", "audit", or "wrap up".

---

## Requirements

- [Claude Code](https://claude.com/claude-code) installed. v2.1.85 or later recommended (earlier versions work — hooks just fire slightly more often than needed).
- Python 3.8 or later on `PATH`. The hooks are stdlib only, nothing to `pip install`.
- macOS, Linux, or Windows.

Optional: `codex`, `gemini`, or `aider` on `PATH` for second-opinion audits. If none are present, audits fall back to an isolated subagent (same model, fresh context).

> [!WARNING]
> Built for multi-phase work. If your task is a typo fix or a single-file change, skip this process.

---

## Using it

The skill auto-triggers on phrases like "new feature", "build phase", "audit", or "wrap up" — so in most sessions you just talk to Claude and it pulls you through the stages. If you want to drive manually, the slash commands map one-to-one onto the flow:

1. **Kick off:** `/chaperone "your idea"` (or `/meta-prompt "your idea"` if you want to skip the router). Claude expands it into a spec and surfaces ambiguities. You answer them in the same turn.

   `/clear`

2. **Plan:** `/plan`. Claude writes a plan file.

   `/clear`

3. **Plan audit:** `/plan-audit`. A fresh context reviews it. You approve the architecture, or loop back to step 2.

   `/clear`

4. **Split:** `/split-phases`. The plan becomes one file per phase, each sized for a single session.

   `/clear`

5. **Phase audit:** `/phase-audit` checks the split, verifies integrity.

   `/clear`

6. **Build:** `/build` — tests first, then implementation.

   `/clear`

7. **Audit the diff:** `/build-audit` (diff-scoped, produces `audit_fix.md`), then `/execute` applies every fix.

   `/clear`

8. **Re-audit, test, ship:** `/re-audit` (caps at 3 loops) → `/test` → `/wrap` (appends to `BUILD_LOG.md`, commits locally, never pushes).

9. **Pause anytime:** `/handoff` writes a self-contained state file so the next session picks up cleanly.

Each command ends by telling you the exact next one to run, so in practice it's one keystroke per gate.

> **Lost mid-workflow?** Run `/chaperone` with no arguments. It reads `plan/current_phase.txt`, shows your current state, and tells you the next command to run. It's deliberately a read-only router — it never auto-advances.

> [!IMPORTANT]
> Don't skip the `/clear` calls. They wipe Claude's memory of the last stage so the next one runs in a fresh context. This is the single biggest quality mechanism in the workflow.

---

> [!NOTE]
> Dormant unless the workflow is active (`plan/current_phase.txt` exists, or pre-phase plan files are present). Dropping the folder into a repo changes nothing until you start a workflow.

---

## Further reading

- [`docs/AUTOMATION.md`](docs/AUTOMATION.md) — what's automated, what isn't, and why
- [`docs/SECOND_OPINION.md`](docs/SECOND_OPINION.md) — integrating `codex`, `gemini`, or `aider` for audits

---

## License

MIT. See `LICENSE`.
