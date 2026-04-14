# Install

After bootstrapping CLAMP Core once with `python3 install_clamp.py`, dry-run this pack with:

```bash
python3 ~/.codex/tools/pack_install.py \
  ~/.codex/packs/TheoryLoop \
  --dry-run
```

Install:

```bash
python3 ~/.codex/tools/pack_install.py \
  ~/.codex/packs/TheoryLoop
```

The installer will:

- back up existing target files under `~/.codex/state/backups/packs/`
- copy the pack sources into their target locations
- run the pack verification commands
- register the installed pack in `~/.codex/state/installed-packs.json`
