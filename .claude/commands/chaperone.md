---
description: Entry point. Start a new workflow from an idea, or show current state + next command.
---

Router command for `claude-chaperone`. Behavior depends on two signals:

1. **Did the user pass arguments?** `$ARGUMENTS` is non-empty vs. empty.
2. **Is the workflow active?** Check for `plan/current_phase.txt`.

Treat `$ARGUMENTS` of `""` (literal empty-string in quotes) as empty. Anything else — including a single word like `help` — counts as arguments; route to Branch A and pass through verbatim.

## Branch A: Arguments provided (new workflow kickoff)

If `$ARGUMENTS` is non-empty:

- If `plan/current_phase.txt` exists, WARN the user: "A workflow is already in progress (Phase N). Starting a new one will not delete the existing plan files, but they will conflict. Either finish the current workflow (`/wrap`) first, or explicitly confirm you want to start over."
- Then (with or without confirmation — that's the user's call): instruct the user to paste `/meta-prompt "$ARGUMENTS"` to begin. Do NOT auto-execute `/meta-prompt`; the user pastes. This preserves the `/clear`-between-stages invariant (see `docs/WORKFLOW.md` Phase 0).

End your response with:

> New workflow starting from: "$ARGUMENTS"
> Paste this to begin: /meta-prompt "$ARGUMENTS"

## Branch B: No arguments, workflow inactive

If `$ARGUMENTS` is empty AND `plan/current_phase.txt` is absent:

Show the user a brief orientation:

- One sentence on what `claude-chaperone` does.
- The full 12-command sequence as a single line (from README.md's flow diagram):
  `/meta-prompt → /plan → /plan-audit → /split-phases → /phase-audit → /build → /build-audit → /execute → /re-audit → /test → /wrap (+ /handoff)`
- An offer: "Tell me what you'd like to build, or run `/chaperone <rough idea>` to kick off."

Keep under 15 lines. Don't lecture — the user can read the README if they want depth.

## Branch C: No arguments, workflow active

If `$ARGUMENTS` is empty AND `plan/current_phase.txt` exists:

Read the state snapshot and show it to the user directly (not as a hook injection). Use the same sources as the `session_start.py` hook — phase number from `plan/current_phase.txt`, `phase_name` from `plan/phase_<N>_scope.json`, last BUILD_LOG entry header from `BUILD_LOG.md`, artifact inventory from `plan/` (files + mtimes), loop counter from `plan/phase_<N>_loop.txt` (if present), escalation flag from `plan/phase_<N>_escalation.md` (if present), and uncommitted-git change count (the hook uses `hu.git_changed_paths` — any equivalent invocation like `git status --porcelain` is fine; if git isn't available, omit the line rather than guess).

Format (visible to the user in Claude's reply):

```
You're on Phase <N>: "<phase_name>"
Last event: <BUILD_LOG header>
On disk: plan/phase_<N>.md <mtime>, plan/phase_<N>_audit_fix.md <mtime>, [...]
Re-audit loop: <M> of 3 [if applicable]
Escalation pending: [YES — user decision needed | NO]
Uncommitted changes: <N> file(s) [omit line if git unavailable]

Suggested next: /<command>
(Paste the command above, or tell me otherwise.)
```

Use the same heuristic the `session_start.py` hook uses to determine "Suggested next". If the next command requires a fresh context, format the suggestion as `Next: /clear then /<command>`.

**Do not execute the suggested command automatically.** The user pastes. This is the same rule as every other `/clear`-gated step — the user owns the transition between stages.

If an escalation is pending (`plan/phase_<N>_escalation.md` exists), surface that as the suggestion rather than a slash command: the user needs to make a decision, not run another stage.

If the stage is ambiguous (no clean heuristic match), say so plainly: "I can't tell what state you're in cleanly. Best next action: open `plan/` and re-read `phase_<N>.md`."

## What NOT to do

- Do NOT run `/meta-prompt`, `/plan`, or any other command yourself. `$ARGUMENTS` is a trigger, not an auto-dispatch.
- Do NOT modify any file in `plan/`. This is a read-only command.
- Do NOT add a BUILD_LOG entry. Running `/chaperone` is not a workflow event.
- Do NOT suggest skipping `/clear`. If the suggested-next command requires a fresh context, the reply must say `Next: /clear then /<command>`.
- Do NOT second-guess the user's arguments. If they pass `"fix a typo"`, pass it through as-is even though the README says trivial changes should skip the workflow. It's the user's choice.
- If the user asks for anything beyond routing or status ("why did the build fail?", "what should I name this?"), tell them to use the relevant specific command (`/build`, `/build-audit`, etc.) instead. `/chaperone` routes and reports — nothing else.
