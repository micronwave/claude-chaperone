# Hooks

Cross-platform Python hooks (Python 3.8+). Referenced from `../../settings.json`. Stdlib only — no third-party dependencies.

## Files

| File | Role |
|---|---|
| `_hook_utils.py` | Shared helpers: stdin payload parsing, scope JSON loading, git-diff reading, structured output emitters, `git push` detection regex. Not a hook itself. |
| `scope_drift_check.py` | PostToolUse (Edit/Write/NotebookEdit) — reads `plan/phase_<N>_scope.json` and warns when edits touch out-of-scope files. LOUD failure on missing/malformed scope. |
| `push_confirm.py` | PreToolUse (Bash) — emits structured `permissionDecision: "ask"` JSON when the Bash command contains `git push`, forcing a user confirmation prompt. |
| `build_log_reminder.py` | UserPromptSubmit — injects a BUILD_LOG reminder into Claude's next turn (via structured `additionalContext` JSON) when code files changed without a log update. Also echoes to stderr for the human. Uses UserPromptSubmit rather than Stop so the reminder actually reaches the agent, not just the terminal. |
| `session_start.py` | SessionStart (new session, resume, and after `/clear`) — injects a factual workflow-state snapshot (current phase, last BUILD_LOG entry, plan/ inventory, suggested next command) into Claude's context so the next turn picks up without the user re-briefing. Silent when plan/ has no workflow markers. |
| `test_hooks.py` | Self-test suite — 40 unit + integration tests covering scope schema, path matching, git-push detection, and every hook script's payload handling + output shape. |

## Activation gate

Every hook reads `plan/current_phase.txt` (via `_hook_utils.read_current_phase`). If the pointer is absent, the hook exits silently — the workflow isn't active, so no enforcement. This means installing the plugin imposes zero friction on unrelated work.

Exception: `session_start.py` also fires when any pre-phase marker (`plan/meta.md`, `plan/plan.md`, `plan/plan_audit.md`, `plan/phase_1.md`) exists, so Claude gets oriented even before `current_phase.txt` is set. When none of those exist, it's silent just like the other hooks.

## Prerequisites

- Python 3.8+ on `PATH`
- The `CLAUDE_PROJECT_DIR` environment variable (Claude Code sets this automatically in recent versions). Hooks fall back to `cwd` if unset.
- git — hooks use `git status --porcelain=v1 -z` to enumerate changed paths.

## Verify your installation

Run the self-test suite:

```
python .claude/hooks/test_hooks.py
```

Expected output: `Ran 43 tests in ...s` followed by `OK`. Any failure indicates a broken install.

### Manual smoke test

For end-to-end verification with the full Claude Code hook pipeline:

1. Create a minimal phase fixture:
   ```bash
   mkdir -p plan
   echo "1" > plan/current_phase.txt
   cat > plan/phase_1_scope.json <<'EOF'
   {
     "schema_version": 1,
     "phase_number": 1,
     "phase_name": "smoke test",
     "scope": {
       "files": ["allowed.py"],
       "prefixes": [],
       "allow_untracked_new": false
     }
   }
   EOF
   ```

2. Ask Claude to edit `out_of_scope.py` — the scope-drift hook should emit a `SCOPE_DRIFT:` warning at end of turn.

3. Ask Claude to run `git push` in a Bash tool call — the push hook should emit a permission prompt before the command runs.

4. Ask Claude to edit `allowed.py` without touching BUILD_LOG.md. On the next user prompt, `build_log_reminder.py` should inject a `REMINDER:` into Claude's context (visible to Claude) and echo the same text to stderr (visible to you in transcript mode, Ctrl-R). If you only see it in the terminal but Claude doesn't mention the reminder on its next turn, check Claude Code version — older versions may drop UserPromptSubmit `additionalContext`.

5. Delete `plan/current_phase.txt` — the three enforcement hooks should go silent on subsequent edits / prompts (workflow inactive). `session_start.py` will still emit at the next session start as long as `plan/meta.md` / `plan/plan.md` / `plan/plan_audit.md` / `plan/phase_1.md` exists; delete those too to fully silence all four.

6. Run `/clear` inside Claude Code with the fixture above in place — in transcript mode (Ctrl-R) you should see a single-line JSON object from `session_start.py` containing `CHAPERONE STATE` text. The next turn's reply should mention the phase number without re-briefing.

If any of these don't fire as described, run the self-test to isolate the break before going further.

## Debugging

Claude Code writes hook execution to a debug log when started with `--debug-file`:

```
claude --debug-file /tmp/claude.log
```

`tail -f /tmp/claude.log` in another terminal shows which hooks matched, their exit codes, stdout, and stderr in real time. Useful when a hook appears not to fire — usually a matcher mismatch or a path issue.

## Design notes

- **Why each hook uses the channel it does.** Per Claude Code spec, each event type has a different "idiomatic" output channel — using the wrong one means the output is silently dropped. PreToolUse: structured JSON for `permissionDecision`, which is why `push_confirm.py` writes JSON. PostToolUse: stderr + exit 0 for warnings, which is why `scope_drift_check.py` writes to stderr. UserPromptSubmit and SessionStart: structured `additionalContext` JSON is the only channel that reaches *Claude* — Stop-hook stdout prints to the terminal but is not added to Claude's conversation. `build_log_reminder.py` therefore fires on UserPromptSubmit (not Stop) so the agent actually sees the reminder, with a stderr echo so the human does too. `session_start.py` fires on SessionStart (not UserPromptSubmit) so the state snapshot only injects once per session start — including after `/clear`, which is the primary use case — instead of on every turn.
- **Why LOUD failure on scope JSON errors?** A scope-drift guard that silently passes every file when the scope is broken is worse than no guard — it gives false confidence. Failing visibly means the user fixes the scope file instead of shipping with a silent blind spot.
- **Why `if: "Bash(git push*)"` in settings?** Performance optimization: the push hook process only spawns on actual push commands (Claude Code v2.1.85+). Earlier versions ignore the `if` field and spawn the hook on every Bash call — the `push_confirm.py` regex handles that case transparently.
