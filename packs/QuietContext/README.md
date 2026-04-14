# QuietContext

`QuietContext` installs the generated task brief and daily quiet-context views used to preload current work without dragging private history into every prompt.

Installed tools:

- `~/.codex/tools/platform_build_context.py`
- `~/.codex/tools/quiet_context.py`

After install, use:

```bash
python3 ~/.codex/tools/platform_build_context.py --topic codex --force
python3 ~/.codex/tools/quiet_context.py
```

## Purpose

This pack turns the recall layer and hot-memory layer into lightweight generated context artifacts that are easy to refresh.
