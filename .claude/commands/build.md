---
description: Execute a phase with strict test-first discipline
---

Load the build system prompt from `.claude/skills/full-build-workflow/references/prompts/build-prompt.md` and follow it. Execute the phase using strict red-green-refactor, appending to `BUILD_LOG.md` at each transition (tests red, implementation green, refactor done).

Inputs for this run:
1. `plan/current_phase.txt` → determines N
2. `plan/phase_<N>.md` (human-readable spec)
3. `plan/phase_<N>_scope.json` (machine-readable scope contract — source of truth for allowed files)
4. `plan/phase_<N-1>_handoff.md` (skip if N=1)
5. `CLAUDE.md`

End your turn with the status block defined in `build-prompt.md`, followed by the next-step pointer:

> Next: `/clear` then `/build-audit`
