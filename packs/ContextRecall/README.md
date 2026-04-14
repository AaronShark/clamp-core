# ContextRecall

`ContextRecall` installs the public-safe CLAMP recall layer.

It indexes:

- Codex sessions from `~/.codex/history.jsonl` and `~/.codex/sessions/`
- canonical memories under `~/.codex/memories/`
- installed skills under `~/.codex/skills/` and `~/.agents/skills/`

Installed tools:

- `~/.codex/tools/retrospect_common.py`
- `~/.codex/tools/recall_common.py`
- `~/.codex/tools/recall_sync.py`
- `~/.codex/tools/recall_query.py`

Installed skills:

- `~/.codex/skills/clamp-core/SKILL.md`
- `~/.codex/skills/clamp-maintenance/SKILL.md`

After install, use:

```bash
python3 ~/.codex/tools/recall_sync.py
python3 ~/.codex/tools/recall_query.py --topic codex --format preload
```

## Purpose

This pack turns cross-session memory recall into a callable local tool instead of a manual review ritual.

## Scope

This pack provides the retrieval substrate used by the rest of CLAMP Core. It does not by itself generate hot context, quiet context, or curation artifacts.
