# Verify

Expected verification steps:

1. Python syntax check succeeds for `platform_build_context.py` and `quiet_context.py`.
2. `platform_build_context.py --topic codex --force` generates `~/.codex/generated/task-brief.md`.
3. `quiet_context.py` generates `~/.codex/generated/daily-brief.md` and `~/.codex/generated/focus-briefs.md`.

Manual spot checks:

```bash
python3 ~/.codex/tools/platform_build_context.py --project ~/.codex --force
python3 ~/.codex/tools/quiet_context.py
```
