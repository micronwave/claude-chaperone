---
description: Apply every finding from audit_fix.md. No judgment, no additions.
---

Read `plan/phase_<N>_audit_fix.md` (N from `plan/current_phase.txt`).

Apply every finding's fix mechanically. Do not re-litigate the audit. Do not add fixes that weren't in the audit. Do not skip fixes you disagree with — disagreements should have been raised as `CONFLICT:` items at audit time, not silently dropped.

For `CONFLICT:` items: if the user has already decided (check conversation context), apply their decision. Otherwise, skip that item and note "awaiting conflict resolution" in BUILD_LOG.

Append to `BUILD_LOG.md`:

```
## <timestamp> — Phase <N> — audit fixes applied (loop <M>)
Findings applied: <N>
Findings skipped (unresolved conflicts): <N>
Files touched: <list>
```

End with:

> Fixes applied. <N> applied, <N> skipped (conflicts). Next: `/clear` then `/re-audit`.
