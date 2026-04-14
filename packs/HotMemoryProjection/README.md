# HotMemoryProjection

`HotMemoryProjection` installs the bounded hot-memory layer used to project compact system, user, and project context into generated markdown artifacts.

Installed tools:

- `~/.codex/tools/user_conclusions.py`
- `~/.codex/tools/hot_context.py`

After install, use:

```bash
python3 ~/.codex/tools/user_conclusions.py refresh
python3 ~/.codex/tools/hot_context.py --topic codex
```

## Purpose

This pack adds a Hermes-style hot layer without creating a second durable memory store.
