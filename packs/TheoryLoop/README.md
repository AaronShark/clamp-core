# TheoryLoop

`TheoryLoop` installs the task-level scaffolding used to externalize success criteria, observations, hypotheses, boundaries, and verification.

Installed tools:

- `~/.codex/tools/theory_loop.py`

After install, use:

```bash
python3 ~/.codex/tools/theory_loop.py start "debug a failing test" --cwd .
python3 ~/.codex/tools/theory_loop.py check --latest --cwd .
```

## Purpose

This pack makes non-trivial engineering work inspectable and curation-friendly instead of leaving the reasoning implicit in the chat log.
