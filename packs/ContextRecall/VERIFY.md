# Verify

Expected verification steps:

1. Python syntax check succeeds for the installed recall tools.
2. `recall_sync.py` rebuilds the recall index without error.
3. `recall_query.py --topic codex --format json` exits successfully even on a fresh machine.

Manual spot checks:

```bash
python3 ~/.codex/tools/recall_query.py --topic "memory" --format preload
python3 ~/.codex/tools/recall_query.py --project ~/.codex --format preload
```
