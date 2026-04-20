---
description: Expand a rough user idea into a detailed requirements spec with ambiguities surfaced
---

Load the meta-prompt system prompt from `.claude/skills/full-build-workflow/references/prompts/meta-prompt.md`.

Follow its workflow precisely:

1. **Archive any prior workflow files.** Before writing anything to `plan/`, move all *files* currently in `plan/` (non-recursively — skip subdirectories like `plan/archive/`) to `plan/archive/<UTC-timestamp>/`, where the timestamp is formatted `YYYYMMDDTHHMMSSZ`. If `plan/` is absent or contains no files, skip this step. Run from the project root via Bash (stdlib-only, cross-platform):

   ```bash
   python -c "import os,shutil,datetime; p='plan'; fl=[f for f in (os.listdir(p) if os.path.isdir(p) else []) if os.path.isfile(os.path.join(p,f))]; arc=os.path.join(p,'archive',datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S.%fZ')); (os.makedirs(arc,exist_ok=True),[shutil.move(os.path.join(p,f),os.path.join(arc,f)) for f in fl]) if fl else None; print(('Archived '+str(len(fl))+' file(s) to '+arc) if fl else 'Nothing to archive')"
   ```

   `workflow_complete.txt` (if present) is among the moved files, so no separate delete step is needed. All chaperone hooks read `plan/` non-recursively and skip subdirectories, so archived files under `plan/archive/` are invisible to them.

2. Perform scoped project research (grep / glob, max 10 file reads).
3. Write `plan/meta.md` using its specified structure.
4. Surface every ambiguity with a suggested default.

The user's raw request: `$ARGUMENTS`

At the end of your response, instruct the user to resolve ambiguities and then run: `/clear` then `/plan`.
