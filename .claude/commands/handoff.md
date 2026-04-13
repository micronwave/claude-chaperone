---
description: Write a standalone handoff file (when /wrap isn't the right fit — mid-phase pause, scope change, manual checkpoint)
---

Write a handoff file that captures the current state of work so a future session (yours or another human's) can resume.

## When to use

- You're pausing mid-phase and want to continue later
- Scope is being reconsidered and you want to checkpoint before changes
- You're handing off to another developer or agent

## Output

Pick the filename by whether the handoff is aligned to a finished phase:

- `plan/phase_<N>_handoff.md` — normal end-of-phase handoff. Usually this is what `/wrap` writes; use this name when `/handoff` is playing that role manually.
- `plan/manual_handoff_<timestamp>.md` — mid-phase pause, scope reconsideration, or any other checkpoint not aligned to a completed phase. Timestamp is UTC, format `YYYYMMDDTHHMMSSZ`.

Use the template at `.claude/skills/full-build-workflow/references/templates/handoff.md` in both cases.

Also append a BUILD_LOG entry:

```
## <timestamp> — Manual handoff
**Reason:** <why we're writing a handoff outside /wrap>
**State:** <tests passing? WIP? blocked?>
**Resume instructions:** <what the next session should do first>
```

End with:

> Handoff written to `<path>`. A future session can resume by reading that file + `CLAUDE.md`.
