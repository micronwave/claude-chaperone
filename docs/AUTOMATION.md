# Automation Reference

What the workflow automates, what it cannot automate, and the workarounds for each unautomatable step.

---

## Fully automated

These happen without any user intervention beyond kicking off the command.

| Step | Mechanism |
|---|---|
| Meta-prompt expansion | `/meta-prompt` — Claude does the research and writes `plan/meta.md` |
| Plan generation | `/plan` — Claude generates full plan from meta |
| Plan audit | `/plan-audit` — Claude audits + patches plan |
| Phase splitting | `/split-phases` — Claude writes N phase files AND N scope JSONs |
| Phase audit | `/phase-audit` — per-phase patching |
| Build | `/build` — test-first execution, build-log appending |
| Build audit | `/build-audit` — diff-scoped comprehensive audit → `audit_fix.md` |
| Execute | `/execute` — applies audit_fix mechanically |
| Re-audit | `/re-audit` — same as build-audit, scoped to the execute diff |
| Test | `/test` — runs project test suite |
| Build log update | Automatic within `/build` + `/wrap` |
| Local commit | `/wrap` — stages + commits |
| Handoff file write | `/wrap` + `/handoff` — writes next-phase state |
| **Scope-drift detection** | `PostToolUse` hook parses `plan/phase_<N>_scope.json` and warns on every edit that touches a file outside the scope contract. LOUD failure if scope JSON is missing/malformed. |
| **Build-log-missing reminder** | `UserPromptSubmit` hook injects a reminder into Claude's next turn (via structured `additionalContext` JSON) when code files changed without a `BUILD_LOG.md` update. Also echoed to stderr for the human. Uses UserPromptSubmit — not Stop — because Stop-hook stdout is not added to Claude's conversation context per spec. |
| **Git-push permission gate** | `PreToolUse` hook emits structured `permissionDecision: "ask"` JSON when the Bash command contains `git push`, forcing the permission dialog. |

---

## Cannot be fully automated (with workarounds)

| Step | Why not | Workaround |
|---|---|---|
| **`/clear` itself** | Only the user can invoke `/clear` — hooks cannot issue slash commands into the user's session. | Every command ends its output with the exact next command for the user to paste: e.g., `"Next: /clear then /plan-audit"`. User paste is a one-keystroke action. Alternative: for audit steps, use **subagents** (`Agent` tool) — they run in an isolated context with the same effect as `/clear` but do not require user action. |
| **Model switching** (Opus ↔ Sonnet) | Claude cannot change the user's active model. | If a command wants a different model, the command surfaces a clear instruction: `"Please switch to Opus with /model opus and re-run this command."` Alternatively, the command delegates to a subagent typed with the desired model. |
| **Architecture approval (post plan-audit)** | By design — this is the most important human decision point. | Command output explicitly stops with `"Review plan/plan.md. Reply 'approved' or describe changes."` User's reply routes the workflow. |
| **Ambiguity resolution (post meta-prompt)** | Requires user's intent, which Claude cannot infer. | `/meta-prompt` lists every ambiguity with Claude's suggested default. User either accepts defaults (one-word reply: "accept") or overrides item by item. |
| **`git push` to a remote** | Destructive to shared state. | `PreToolUse` hook emits `permissionDecision: "ask"` — user gets the standard permission dialog and clicks through once per push. Never bypassed by any Claude action. |
| **Re-fix escalation on max loops** | At 3 loops, the remaining issues are judgment calls, not mechanical fixes. | `/re-audit` stops the loop, writes `plan/phase_<N>_escalation.md`, and asks user: accept / refactor / defer. Full escalation format and trigger list live in `.claude/skills/full-build-workflow/SKILL.md` under "When to escalate to the user". |
| **Scope-drift resolution** | When the hook flags out-of-scope edits, only the user can decide whether the drift is legitimate. | Hook emits a structured warning at end of turn with the drift list + three options. User replies with the decision. |
| **Second-opinion tool install** | Installing `codex` / `gemini` / `aider` CLIs is a system-level change requiring user permission. | Workflow auto-detects what's on `PATH`. Uses what it finds; falls back to subagent audit if nothing is available. Never prompts the user to install. |
| **Deciding when to stop the workflow entirely** | If the build is fundamentally wrong, a new plan is needed — Claude cannot know that from inside a phase. | Any command can surface a `SCOPE_RECONSIDER_NEEDED` signal in its output if it detects a violation of the meta-prompt's intent. User then re-enters from `/plan` or `/meta-prompt`. |

---

## Hook details

### `scope_drift_check.py` (PostToolUse on Edit/Write/NotebookEdit)

Reads `plan/current_phase.txt` to get the active phase number N, then loads `plan/phase_<N>_scope.json` using the strict schema defined at `.claude/skills/full-build-workflow/references/templates/SCOPE_SCHEMA.md`. Runs `git status --porcelain=v1 -z` to enumerate every changed path. For each path, checks:

1. Is it in the universal allowlist (BUILD_LOG.md, plan/phase_<N>_* files, plan/.build_log_reminder_state)? → in scope
2. Does it match an exact entry in `scope.files`? → in scope
3. Does it start with any entry in `scope.prefixes` (all of which must end in `/`)? → in scope
4. Is it an untracked new file AND under a prefix AND `scope.allow_untracked_new` is true? → in scope
5. Otherwise → drift

Drift emits a structured warning to stderr:

```
SCOPE_DRIFT: files changed outside Phase <N> (<phase_name>) declared scope:
  [M] path/to/file_1.py
  [M] path/to/file_2.py
Decide: (a) accept drift — update plan/phase_<N>_scope.json to include these paths, (b) revert the changes, (c) amend and continue with an explicit justification in BUILD_LOG.
```

**LOUD failure modes (not silent):** missing scope JSON, malformed JSON, schema violation, phase-number mismatch, or a prefix entry without a trailing slash all emit `SCOPE_DRIFT_HOOK_ERROR: <code>: <details>` so the user fixes the scope file rather than shipping with a silently broken guard.

Non-blocking — emits the warning but exits 0 so the edit itself isn't rejected. Post-hoc revert is easier than fighting a blocked-edit.

### `push_confirm.py` (PreToolUse on Bash)

Reads the stdin payload per Claude Code hook spec:

```json
{
  "tool_name": "Bash",
  "tool_input": { "command": "<the shell command>" }
}
```

If `tool_name` is not `Bash` or `tool_input.command` is empty, exits silently. Otherwise checks the command against a regex that handles:

- Basic: `git push`, `git push origin main --force`
- With env prefix: `GIT_ASKPASS=foo git push`
- Chained: `cd x && git push`, `foo; git push`, `(git push)`
- Quoted: `"git" push`, `'git' push`
- Windows: `git.exe push`

On match, emits structured JSON output per the hook spec:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "git push is destructive to the shared remote. Review the command and confirm before proceeding."
  }
}
```

Claude Code treats this as a "show the user the permission prompt" response. User clicks Allow/Deny per push. No environment variable hacks, no in-command sentinels. All state lives in the permission dialog the user sees.

Configured in `settings.json` with `"if": "Bash(git push*)"` — on Claude Code v2.1.85+, this narrows hook process spawning to push commands only. Earlier versions ignore `if` and spawn the hook on every Bash call; the regex handles that case transparently.

### `build_log_reminder.py` (UserPromptSubmit)

On every user prompt submit, checks if code files (anything outside `plan/` and `BUILD_LOG.md`) have been modified without a corresponding BUILD_LOG entry. If so, emits the reminder on two channels:

1. **Primary — structured JSON on stdout** with `hookSpecificOutput.hookEventName: "UserPromptSubmit"` and `hookSpecificOutput.additionalContext: "<reminder text>"`. Claude Code adds this to Claude's context for the current turn, so the agent actually reads the reminder and can act on it.
2. **Secondary — stderr** so the human sees the same reminder in transcript mode (Ctrl-R). Redundant by design: if the structured-JSON injection is silently dropped by a given Claude Code version (see anthropics/claude-code#13912), the human still gets the nudge.

**Why UserPromptSubmit, not Stop?** Per the Claude Code hook spec, Stop-hook stdout prints to the user's terminal but is NOT added to Claude's conversation. Only `UserPromptSubmit` and `SessionStart` output reaches the agent. A Stop-based reminder only nudges the human — which defeats the purpose of a hook whose job is to keep the agent honest about logging. No `stop_hook_active` guard is needed; UserPromptSubmit does not loop.

Non-blocking — always exits 0 even on malformed stdin, so a hook bug can never reject the user's prompt.

State file: `plan/.build_log_reminder_state` — single-line cache of `BUILD_LOG.md`'s mtime at last injection, used to suppress repeat nudges between updates. Safe to delete; will be recreated on next fire. Add `plan/` to your project's `.gitignore` to avoid tracking workflow scratch state.

---

## Failure modes & degradation

| Condition | Effect |
|---|---|
| `plan/current_phase.txt` missing | All hooks silent. Workflow inactive — no enforcement imposed. |
| `plan/phase_<N>_scope.json` missing or malformed | `scope_drift_check.py` emits `SCOPE_DRIFT_HOOK_ERROR` to stderr. User sees it. Scope enforcement is OFF until fixed. **Deliberately loud.** |
| Python not installed | Claude Code logs "hook error" and continues. Workflow becomes advisory — commands still work, guards go silent. User is responsible for noticing absent reminders. |
| Git not available | `git_changed_paths()` returns empty list; hooks assume nothing changed and skip. (Rare — Claude Code requires git for most workflows.) |
| Hook spec version mismatch | If Claude Code changes the stdin JSON schema, `push_confirm.py` and `build_log_reminder.py` may fail to parse fields. Both default to no-op in that case — safer than bad enforcement. `scope_drift_check.py` doesn't depend on payload fields, so it's unaffected. |

Recommended post-install validation: run `python .claude/hooks/test_hooks.py`. All 25 tests should pass. Any failure indicates a broken install.
