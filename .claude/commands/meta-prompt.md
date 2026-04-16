---
description: Expand a rough user idea into a detailed requirements spec with ambiguities surfaced
---

Load the meta-prompt system prompt from `.claude/skills/full-build-workflow/references/prompts/meta-prompt.md`.

Follow its workflow precisely:

1. If `plan/workflow_complete.txt` exists, delete it (starting a new workflow supersedes the prior completion marker).
2. Perform scoped project research (grep / glob, max 10 file reads).
3. Write `plan/meta.md` using its specified structure.
4. Surface every ambiguity with a suggested default.

The user's raw request: `$ARGUMENTS`

At the end of your response, instruct the user to resolve ambiguities and then run: `/clear` then `/plan`.
