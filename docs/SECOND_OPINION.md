# Second-Opinion Tools (Optional)

`/build-audit` and `/re-audit` can optionally invoke an external AI coding tool for an independent audit pass. **This is entirely optional** — if none of the supported tools are available, the workflow falls back to an isolated subagent audit (same model, fresh context) which is still materially better than a same-session self-audit.

---

## Supported tools

The audit commands probe `PATH` in this order and use the first tool found:

| Priority | Tool | CLI name | Notes |
|---|---|---|---|
| 1 | OpenAI Codex CLI | `codex` | Strong at bug-finding on diffs |
| 2 | Google Gemini CLI | `gemini` | Good at style and consistency |
| 3 | Aider | `aider` | Broad language support |

If none are available, the command uses the fallback pattern (subagent audit).

---

## What gets sent to the second-opinion tool

The audit commands construct an invocation like:

```bash
<tool> --diff <git-diff-output> --prompt "$(cat .claude/skills/full-build-workflow/references/prompts/audit-prompt.md)"
```

Only the **diff** of the current scope is sent — not the whole project. This keeps:

- Token cost bounded
- Third-party data exposure minimized (only the code you just changed)
- Audit signal focused on the actual change

---

## How findings are merged

1. The second-opinion tool emits its findings to stdout.
2. Claude reads its output and merges it into a unified `audit_fix.md` alongside Claude's own findings.
3. Duplicates are deduped by file+line+issue-type.
4. Conflicts (Claude says X, second tool says not-X) are surfaced to the user as `CONFLICT:` items for manual resolution.

---

## Fallback: subagent audit

If no external tool is on `PATH`:

```
Agent(
  description: "Independent audit pass",
  subagent_type: "general-purpose",
  prompt: "Audit the following diff as if you had never seen this code before..."
)
```

The subagent runs in an isolated context — it does not inherit the build session's assumptions or shortcuts. Empirically this catches ~60-70% of what a different model would catch, because many audit misses come from the session's self-reinforcing narrative rather than from the model's fundamental blind spots.

---

## Configuration

Set in `.claude/skills/full-build-workflow/references/prompts/audit-prompt.md` — the system prompt passed to whichever tool runs.

To **disable** second-opinion entirely (force subagent fallback), set environment variable:

```
export CBW_DISABLE_SECOND_OPINION=1
```

Useful if your second-opinion tool is flaky, rate-limited, or you want reproducible audits across machines.

---

## Privacy / data-egress note

Sending your diff to a third-party tool sends your code to that tool's backend. Consult your employer's policy before enabling on work projects. The fallback subagent path keeps everything inside your existing Claude Code session — no additional data egress.
