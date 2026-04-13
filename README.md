```
   ┌──────────────────────────────────────────────┐
   │   claude-chaperone                           │
   │   guardrails for Claude Code                 │
   │   plan · test · audit · stop                 │
   └──────────────────────────────────────────────┘
```

**What it is:** a set of slash commands, hooks, and a skill you copy into any project. Once installed, Claude Code has to follow a structured build flow instead of one-shotting a feature and leaving you to clean up.

**What you do:** make the architecture calls, approve the plan, `/clear` between stages.
**What Claude does:** the mechanical work, test-first, inside a declared scope, with its own diff audited before you see it.

`v0 / skeleton · stdlib-only hooks · MIT`

---

## Why this exists

Claude Code is great until the session gets long. Then the failure modes kick in:

| Problem | What it looks like |
|---|---|
| Context rot | Quality slides as the conversation fills up |
| Scope drift | "Helpful" edits to code you didn't ask about |
| Self-audit blind spots | Reviewing its own work, it misses the same things twice |
| Lost state | New session guesses where the last one stopped |
| Infinite polish | Audit, fix, audit, fix, with no exit |
| Forgotten discipline | Build logs, commits, handoffs skipped under pressure |

This repo has an opinionated answer for each.

---

## What's in the box

**Twelve slash commands**, one per stage. You `/clear` between them so each runs in a fresh context:

```
/meta-prompt  →  /plan  →  /plan-audit  →  /split-phases  →  /phase-audit
                                                                   ↓
             /wrap  ←  /test  ←  /re-audit  ←  /execute  ←  /build-audit  ←  /build
```

**Three hooks**, pure Python stdlib, no install step:

- `scope_drift_check.py` warns at end of turn if edits left the phase scope
- `push_confirm.py` forces a permission prompt on `git push`
- `build_log_reminder.py` nags when code changes have outrun `BUILD_LOG.md`

All three no-op unless `plan/current_phase.txt` exists, so the workflow is dormant in projects that haven't opted in.

**One skill** that auto-triggers the whole sequence on phrases like "new feature", "build phase", "do an audit", or "wrap up".

---

## Quick start

```bash
# 0. Clone the repo
git clone https://github.com/micronwave/claude-chaperone.git

# 1. Copy into your project (merge if a .claude/ already exists)
cp -r claude-chaperone/.claude your-project/
cp claude-chaperone/settings.json your-project/.claude/settings.json

# 2. Paste the CLAUDE.md.snippet contents into your project's CLAUDE.md

# 3. Start a fresh Claude Code session
/meta-prompt "rough idea of what you want to build"
```

That's it. From there the skill pulls you through the stages. Between every stage you'll run `/clear` — a built-in Claude Code command that wipes session context. Each command ends by telling you the exact next one to paste, so it's one keystroke per gate.

---

## The full flow

```mermaid
flowchart TD
    A[Initial prompt] --> B[/meta-prompt/]
    B --> B2{"Ambiguities<br/>surfaced?"}
    B2 -->|Yes| B3[User resolves]
    B2 -->|No| C[/clear/]
    B3 --> C
    C --> D[/plan/]
    D --> E[/clear/]
    E --> F[/plan-audit/]
    F --> F2{"User approves<br/>architecture?"}
    F2 -->|No| D
    F2 -->|Yes| G[/clear/]
    G --> H[/split-phases/]
    H --> I[/clear/]
    I --> J[/phase-audit/]
    J --> K[Per phase loop]

    K --> L[/clear/]
    L --> M[/"build<br/>tests first"/]
    M --> M2{"Scope drift<br/>hook OK?"}
    M2 -->|No| M3[User decides]
    M2 -->|Yes| N[/clear/]
    M3 --> N
    N --> O[/"build-audit<br/>diff-scoped, thorough"/]
    O --> P[/"execute<br/>apply audit_fix"/]
    P --> Q[/clear/]
    Q --> R[/re-audit]
    R --> R2{Issues?}
    R2 -->|"Yes, <3 loops"| P
    R2 -->|"Yes, ≥3 loops"| R3[Escalate to user]
    R2 -->|No| S[/test/]
    R3 --> S
    S --> S2{Pass?}
    S2 -->|No| P
    S2 -->|Yes| T[/"wrap<br/>build log + commit"/]
    T --> U{More phases?}
    U -->|Yes| L
    U -->|No| V[Done]
```

---

## Repo layout

```
claude-chaperone/
├── README.md
├── CLAUDE.md.snippet              ← paste into your project's CLAUDE.md
├── settings.json                  ← hooks registration
├── docs/
│   ├── WORKFLOW.md                ← full rationale + gate definitions
│   ├── AUTOMATION.md              ← what is and isn't automated, and why
│   └── SECOND_OPINION.md          ← optional external-tool integration
└── .claude/
    ├── skills/full-build-workflow/
    │   ├── SKILL.md               ← orchestration + keyword triggers
    │   └── references/
    │       ├── templates/         ← plan, handoff, audit_fix, build_log
    │       └── prompts/           ← reusable prompt fragments
    ├── commands/                  ← the 12 slash commands
    └── hooks/                     ← scope-drift, push-confirm, log-nag
```

---

## The eight rules it enforces

1. A phase fits one session, or it gets split.
2. `/clear` between every stage. Stale context is the #1 quality killer.
3. State lives in handoff files, not conversation memory.
4. Audits are scope-bounded, but within scope nothing gets sampled.
5. Re-fix loops cap at 3. After that, the human gets pulled back in.
6. You own architecture. Claude owns execution.
7. `git push` always needs a human click. No auto-push, ever.
8. Second-opinion tools (`codex`, `gemini`, `aider`) are welcome but optional. If none are on `PATH`, audits fall back to a fresh subagent.

The reasoning behind each lives in `docs/WORKFLOW.md`.

---

## License

MIT. See `LICENSE`.
