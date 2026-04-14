# CLAMP Core

[![smoke-test](https://github.com/AaronShark/clamp-core/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/AaronShark/clamp-core/actions/workflows/smoke-test.yml)

Install the CLAMP runtime into Codex without shipping anyone else's memory.

`CLAMP Core` is the public, portable layer of the `Codex Local Augmented Memory Platform`. It packages the reusable runtime only: recall, hot context, curation, and quiet task-start context assembly. It does not include private memories, session archives, or personal user profiles.

## Why This Exists

Codex can already read files, search repos, and follow skills. What it does not have by default is a lightweight local memory operating layer that can:

- rebuild a local recall index over sessions, memories, and skills
- generate bounded hot context instead of loading large instruction blobs
- stage reusable conclusions and procedures at task boundaries
- produce quiet daily and task-level context artifacts for reuse
- install and verify those behaviors as composable packs instead of ad hoc scripts

`CLAMP Core` is that layer, packaged so another Codex user can install it in one step.

## What You Get

After installation, the repo syncs public CLAMP packs into `~/.codex/packs/`, installs runtime tools into `~/.codex/tools/`, and installs public CLAMP skills into `~/.codex/skills/`.

Included packs:

| Pack | Outcome |
| --- | --- |
| `ContextRecall` | Rebuild and query a local recall index over sessions, memories, and skills |
| `TheoryLoop` | Scaffold explicit success judges, observations, hypotheses, boundaries, and verification |
| `HotMemoryProjection` | Generate bounded system, user, and project hot-context artifacts |
| `CurationLoop` | Stage reusable conclusions and procedure candidates close to task boundaries |
| `QuietContext` | Generate task briefs, focus briefs, and a low-noise daily context view |

Installed public skills:

- `clamp-core`
- `clamp-maintenance`

## One-Minute Install

```bash
git clone https://github.com/AaronShark/clamp-core.git
cd clamp-core
python3 install_clamp.py
```

Dry run:

```bash
python3 install_clamp.py --dry-run
```

The bootstrap installer will:

1. sync pack sources into `~/.codex/packs/`
2. install or update runtime tools under `~/.codex/tools/`
3. install public CLAMP skills under `~/.codex/skills/`
4. run pack verification commands unless `--no-verify` is passed
5. register installed packs in `~/.codex/state/installed-packs.json`

## What It Feels Like After Install

Useful commands:

```bash
python3 ~/.codex/tools/recall_sync.py
python3 ~/.codex/tools/recall_query.py --topic codex --format preload
python3 ~/.codex/tools/hot_context.py --topic codex
python3 ~/.codex/tools/curation_queue.py refresh
python3 ~/.codex/tools/platform_build_context.py --topic codex --force
python3 ~/.codex/tools/quiet_context.py
```

The intended behavior shift is:

- starting a task becomes a recall problem, not a memory test
- task context becomes generated runtime state, not manual prompt sprawl
- reusable conclusions and procedures stop getting stranded in chat history
- installing memory behavior becomes a pack install, not a hand-copied ritual

## Public vs Private Boundary

`CLAMP Core` is explicitly public-safe. It does not ship:

- `~/.codex/memories/` contents
- `~/.codex/history.jsonl`
- `~/.codex/sessions/`
- `~/.codex/user-work-profile.md`
- personal captures
- private document archives
- full-fidelity memory backup or migration data

This repo installs the runtime, not the user's memory vault.

## Why It Is A Repo Instead Of A Single Skill

A single skill is not enough for this boundary. `CLAMP Core` needs:

- multiple runtime tools with dependencies between them
- an install order
- verification commands
- versioned pack manifests
- upgrade-safe copying into `~/.codex`
- a public distribution surface that other Codex users can clone and install directly

That is why the packaging unit here is `repo + bootstrap installer + capability packs`, with skills included as one installed surface inside the runtime.

## Upgrade Model

To upgrade, pull a fresh checkout and rerun:

```bash
python3 install_clamp.py
```

This keeps the public runtime easy to refresh while leaving private memory outside the repo boundary.

## Verification And CI

The repository is structured so a clean machine can validate the public runtime without any private CLAMP data:

- syntax-check all bundled Python
- run `install_clamp.py --dry-run`
- run a full isolated install with `HOME` and `CODEX_HOME` pointed at a temporary directory

The same flow is wired into GitHub Actions through `smoke-test.yml`.

## Who This Is For

`CLAMP Core` is for:

- Codex users who want a reusable local memory runtime
- people who want installable recall and context assembly without adopting someone else's private memory tree
- users who want to keep public runtime packaging separate from private backup or vault migration

It is not yet the full answer for private memory sync across machines. That should stay a separate vault export/import workflow.

## FAQ

**Does this install your memory?**

No. It installs the CLAMP runtime only.

**Can another user click one GitHub link and get the functionality?**

Yes. That is the purpose of this repo.

**Can I use this to migrate my whole private CLAMP to another machine?**

Not by itself. `CLAMP Core` is the public runtime layer. Private history and memories should use a separate private backup or vault flow.

**Can I install only part of it?**

Yes.

```bash
python3 install_clamp.py --only ContextRecall
python3 install_clamp.py --only QuietContext
```

## Current Scope

`v0.1.0` is the first public scaffold. It is already usable, but still intentionally narrow:

- public-safe runtime only
- pack-based installation and verification
- no bundled private memory content
- no private vault export/import workflow

If you want the reusable behavior without the private state, this is the correct boundary.
