# Verify

Expected verification steps:

1. Python syntax check succeeds for `theory_loop.py`.
2. `theory_loop.py list --limit 1 --json` exits successfully.
3. `theory_loop.py start ...` creates a note under `~/.codex/generated/theory-loops/`.

Manual spot checks:

```bash
python3 ~/.codex/tools/theory_loop.py list --limit 5
python3 ~/.codex/tools/theory_loop.py start "scaffold a new CLAMP pack" --cwd ~/.codex --verify "python3 -m py_compile ~/.codex/tools/theory_loop.py"
```
