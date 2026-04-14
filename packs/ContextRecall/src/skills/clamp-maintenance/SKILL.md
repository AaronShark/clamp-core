---
name: clamp-maintenance
description: Use when the task is to refresh, verify, repair, or review the health of an installed CLAMP Core runtime.
contract_version: 1
status: canonical
domain: collaboration-memory
---

Use this skill when the runtime is installed but needs verification or repair.

## Core Checks

Run these in order:

```bash
python3 ~/.codex/tools/recall_sync.py
python3 ~/.codex/tools/user_conclusions.py refresh
python3 ~/.codex/tools/curation_queue.py refresh
python3 ~/.codex/tools/quiet_context.py
```

## Pack-Level Repair

If one capability pack looks stale or broken, reinstall it through the pack installer:

```bash
python3 ~/.codex/tools/pack_install.py ~/.codex/packs/<PackName>
```

Useful pack names:

- `ContextRecall`
- `TheoryLoop`
- `HotMemoryProjection`
- `CurationLoop`
- `QuietContext`

## Boundary

- Repair the shared runtime and generated artifacts.
- Do not treat private memory export, backup, or migration as part of CLAMP Core.
