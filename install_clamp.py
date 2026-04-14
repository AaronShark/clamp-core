from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


PACK_ORDER = (
    "ContextRecall",
    "TheoryLoop",
    "HotMemoryProjection",
    "CurationLoop",
    "QuietContext",
)
PACK_DEPENDENCIES = {
    "ContextRecall": set(),
    "TheoryLoop": {"ContextRecall"},
    "HotMemoryProjection": {"ContextRecall"},
    "CurationLoop": {"ContextRecall", "TheoryLoop"},
    "QuietContext": {"ContextRecall", "TheoryLoop", "HotMemoryProjection", "CurationLoop"},
}

HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser().resolve()
REPO_ROOT = Path(__file__).resolve().parent
BOOTSTRAP_ROOT = REPO_ROOT / "src" / "bootstrap"
PACKS_ROOT = REPO_ROOT / "packs"
CODEX_TOOLS = CODEX / "tools"
CODEX_PACKS = CODEX / "packs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the public CLAMP Core runtime into ~/.codex.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned operations without writing.")
    parser.add_argument("--no-verify", action="store_true", help="Skip pack verification commands.")
    parser.add_argument(
        "--only",
        action="append",
        choices=PACK_ORDER,
        help="Install only one or more named packs. Dependencies still resolve from ~/.codex/packs.",
    )
    return parser.parse_args()


def selected_packs(args: argparse.Namespace) -> list[str]:
    requested = list(dict.fromkeys(args.only or []))
    return requested or list(PACK_ORDER)


def root_packs(pack_names: list[str]) -> list[str]:
    selected = set(pack_names)
    covered: set[str] = set()
    for pack_name in pack_names:
        covered.update(PACK_DEPENDENCIES.get(pack_name, set()) & selected)
    return [pack_name for pack_name in pack_names if pack_name not in covered]


def print_step(message: str) -> None:
    print(message, flush=True)


def ensure_dir(path: Path, *, dry_run: bool) -> None:
    print_step(f"ensure-dir {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def copy_file(source: Path, target: Path, *, dry_run: bool) -> None:
    print_step(f"copy-file {source} -> {target}")
    if dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_tree(source: Path, target: Path, *, dry_run: bool) -> None:
    print_step(f"copy-tree {source} -> {target}")
    if dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)


def sync_bootstrap_tools(*, dry_run: bool) -> None:
    ensure_dir(CODEX_TOOLS, dry_run=dry_run)
    for name in ("pack_common.py", "pack_install.py"):
        copy_file(BOOTSTRAP_ROOT / name, CODEX_TOOLS / name, dry_run=dry_run)


def sync_pack_sources(*, dry_run: bool) -> None:
    ensure_dir(CODEX_PACKS, dry_run=dry_run)
    for pack_name in PACK_ORDER:
        copy_tree(PACKS_ROOT / pack_name, CODEX_PACKS / pack_name, dry_run=dry_run)


def run_command(argv: list[str]) -> int:
    print_step(f"$ {shlex.join(argv)}")
    completed = subprocess.run(argv, check=False)
    return completed.returncode


def install_selected_packs(*, pack_names: list[str], dry_run: bool, no_verify: bool) -> int:
    installer = BOOTSTRAP_ROOT / "pack_install.py"
    for pack_name in pack_names:
        pack_root = (PACKS_ROOT if dry_run else CODEX_PACKS) / pack_name
        command = [sys.executable, str(installer), str(pack_root)]
        if dry_run:
            command.append("--dry-run")
        if no_verify:
            command.append("--no-verify")
        rc = run_command(command)
        if rc != 0:
            return rc
    return 0


def main() -> int:
    args = parse_args()
    pack_names = selected_packs(args)
    install_roots = root_packs(pack_names)

    print_step(f"repo-root {REPO_ROOT}")
    print_step(f"codex-home {CODEX}")
    print_step(f"selected-packs {', '.join(pack_names)}")
    print_step(f"install-roots {', '.join(install_roots)}")

    sync_bootstrap_tools(dry_run=args.dry_run)
    sync_pack_sources(dry_run=args.dry_run)

    rc = install_selected_packs(
        pack_names=install_roots,
        dry_run=args.dry_run,
        no_verify=args.no_verify,
    )
    if rc != 0:
        return rc

    print_step("clamp core install complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
