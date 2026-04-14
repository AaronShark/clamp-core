# CurationLoop

`CurationLoop` installs the task-end curation queue and procedure candidate extraction flow.

Installed tools:

- `~/.codex/tools/procedure_candidates.py`
- `~/.codex/tools/curation_queue.py`

After install, use:

```bash
python3 ~/.codex/tools/curation_queue.py refresh
python3 ~/.codex/tools/curation_queue.py list
```

## Purpose

This pack stages reusable facts and procedures close to task boundaries instead of relying only on retrospective cleanup.
