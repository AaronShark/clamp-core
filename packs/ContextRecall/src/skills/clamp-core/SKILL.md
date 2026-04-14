---
name: clamp-core
description: Use when the task involves CLAMP Core packs, local recall, hot context, quiet context, or public installation and verification of the CLAMP runtime.
contract_version: 1
status: canonical
domain: collaboration-memory
---

Use this skill when the user is working on the shared CLAMP runtime rather than private memories.

## Installed Tools

- `~/.codex/tools/recall_sync.py`
- `~/.codex/tools/recall_query.py`
- `~/.codex/tools/hot_context.py`
- `~/.codex/tools/platform_build_context.py`
- `~/.codex/tools/quiet_context.py`

## Default Flow

1. Refresh the recall index first if the machine has new sessions, memories, or skills:

```bash
python3 ~/.codex/tools/recall_sync.py
```

2. For a concrete topic, inspect the recall layer before freehand reconstruction:

```bash
python3 ~/.codex/tools/recall_query.py --topic "<topic>" --format preload
```

3. For active task startup, prefer generated context artifacts over manually loading large instruction blobs:

```bash
python3 ~/.codex/tools/platform_build_context.py --topic "<topic>" --force
python3 ~/.codex/tools/quiet_context.py
```

## Boundary

- CLAMP Core is the public runtime and packaging layer.
- It does not include private memories, session history exports, or user-specific profile files.
