# Verify

Expected verification steps:

1. Python syntax check succeeds for `procedure_candidates.py` and `curation_queue.py`.
2. `curation_queue.py refresh` completes without error.
3. `curation_queue.py list --json` emits a JSON array or markdown summary.

Manual spot checks:

```bash
python3 ~/.codex/tools/curation_queue.py refresh
python3 ~/.codex/tools/curation_queue.py list --json
```
