# CLAMP Core

`CLAMP Core` is a public-safe distribution of the `Codex Local Augmented Memory Platform`.

It packages the reusable runtime layer only:

- recall indexing and query
- theory-loop scaffolding
- hot-memory projection
- task-end curation
- generated quiet-context artifacts

It explicitly does not ship private user state:

- `~/.codex/memories/` contents
- `~/.codex/history.jsonl`
- `~/.codex/sessions/`
- `~/.codex/user-work-profile.md`
- personal captures or private document archives

## Quick Start

```bash
git clone https://github.com/AaronShark/clamp-core.git
cd clamp-core
python3 install_clamp.py
```

Dry run:

```bash
python3 install_clamp.py --dry-run
```

After install, CLAMP Core syncs its pack sources into `~/.codex/packs/`, installs runtime tools into `~/.codex/tools/`, and installs public CLAMP skills into `~/.codex/skills/`.

## Packs

- `ContextRecall`: rebuild and query a local recall index over sessions, memories, and skills
- `TheoryLoop`: scaffold explicit success judges, hypotheses, boundaries, and verification notes
- `HotMemoryProjection`: generate bounded system, user, and project hot-context artifacts
- `CurationLoop`: stage reusable facts and procedures at task boundaries
- `QuietContext`: generate task briefs, focus briefs, and a lightweight daily context view

## Verification

Useful commands after install:

```bash
python3 ~/.codex/tools/recall_sync.py
python3 ~/.codex/tools/hot_context.py --topic codex
python3 ~/.codex/tools/curation_queue.py refresh
python3 ~/.codex/tools/quiet_context.py
```

## Upgrade Model

Re-run the installer from a fresh checkout:

```bash
python3 install_clamp.py
```

The bootstrap installer will:

- sync the public pack sources into `~/.codex/packs/`
- install or update the CLAMP runtime tools
- run each pack's verification commands unless `--no-verify` is passed
- register installed packs under `~/.codex/state/installed-packs.json`

## Non-Goals

- exporting or syncing private memory archives
- full-fidelity migration of personal CLAMP history between machines
- shipping user-specific rules, profiles, or personal captures

Those flows should live in a separate private backup or vault workflow.

## CI

The repo is structured so a clean machine can validate the public runtime without any private CLAMP data:

- syntax-check all bundled Python
- run `install_clamp.py --dry-run`
- run a full isolated install with `HOME` and `CODEX_HOME` pointed at a temporary directory
