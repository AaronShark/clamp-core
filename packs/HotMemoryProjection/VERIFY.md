# Verify

Expected verification steps:

1. Python syntax check succeeds for `user_conclusions.py` and `hot_context.py`.
2. `user_conclusions.py refresh` completes without error.
3. `hot_context.py --topic codex` generates `~/.codex/generated/hot-context/manifest.json`.

Manual spot checks:

```bash
python3 ~/.codex/tools/user_conclusions.py list --limit 12
python3 ~/.codex/tools/hot_context.py --project ~/.codex
```
