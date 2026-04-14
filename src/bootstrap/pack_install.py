from __future__ import annotations

import argparse
import json
from pathlib import Path

from pack_common import (
    PACK_BACKUP_ROOT,
    backup_target,
    pack_manifest_id,
    install_target,
    load_pack,
    pack_targets,
    path_snapshot,
    register_install,
    resolve_dependency_path,
    restore_target,
    run_verify_commands,
    utc_stamp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a local Codex pack.")
    parser.add_argument("pack", help="Pack directory or pack.json path.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned file operations without writing.")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-install verification commands.")
    return parser.parse_args()


def install_pack(
    *,
    pack_path: str,
    dry_run: bool,
    no_verify: bool,
    installed_this_run: set[str],
    active_stack: set[str],
) -> int:
    pack_root, manifest = load_pack(pack_path)
    pack_id = pack_manifest_id(manifest, pack_root)
    version = str(manifest.get("version") or "0.0.0")

    if pack_id in active_stack:
        raise RuntimeError(f"circular dependency detected while installing `{pack_id}`")
    if pack_id in installed_this_run:
        print(f"pack already handled in this run: {pack_id}")
        return 0

    active_stack.add(pack_id)
    try:
        for dependency in manifest.get("dependencies", []):
            dependency_text = str(dependency or "").strip()
            if not dependency_text:
                continue
            dependency_root = resolve_dependency_path(pack_root, dependency_text)
            print(f"dependency: {dependency_text} -> {dependency_root}")
            rc = install_pack(
                pack_path=str(dependency_root),
                dry_run=dry_run,
                no_verify=no_verify,
                installed_this_run=installed_this_run,
                active_stack=active_stack,
            )
            if rc != 0:
                return rc

        targets = pack_targets(pack_root, manifest)
        install_stamp = utc_stamp()
        backup_root = PACK_BACKUP_ROOT / f"{install_stamp}-{pack_id}"

        print(f"pack: {pack_id} v{version}")
        print(f"root: {pack_root}")
        print(f"targets: {len(targets)}")

        backups: list[dict[str, str]] = []
        installed: list[dict[str, str]] = []
        restore_plan: list[tuple[str, object]] = []

        try:
            for target in targets:
                before = path_snapshot(target.target)
                after = path_snapshot(target.source)
                print(f"- {target.raw_from} -> {target.target}")
                print(f"  source: {after}")
                print(f"  target-before: {before}")
                if dry_run:
                    continue
                backup_path = backup_target(target.target, backup_root)
                restore_plan.append((str(target.target), backup_path))
                install_target(target)
                installed.append({"from": target.raw_from, "to": str(target.target)})
                if backup_path is not None:
                    backups.append({"target": str(target.target), "backup": str(backup_path)})

            if dry_run:
                print("dry-run complete")
                installed_this_run.add(pack_id)
                return 0

            verify_results: list[dict[str, object]] = []
            if not no_verify:
                verify_results = run_verify_commands(pack_root=pack_root, manifest=manifest)
                if any(result["exit_code"] != 0 for result in verify_results):
                    raise RuntimeError("verification failed")

            record = {
                "id": pack_id,
                "version": version,
                "description": str(manifest.get("description") or "").strip(),
                "source_path": str(pack_root),
                "installed_at": install_stamp,
                "backups": backups,
                "targets": installed,
                "verify_results": [
                    {
                        "command": result["command"],
                        "exit_code": result["exit_code"],
                    }
                    for result in verify_results
                ],
                "manifest": {
                    "dependencies": list(manifest.get("dependencies") or []),
                },
            }
            register_install(record)
            installed_this_run.add(pack_id)
            print(json.dumps(record, ensure_ascii=False, indent=2))
            print("pack install complete")
            return 0
        except Exception as exc:
            print(f"pack install failed: {pack_id}: {exc}")
            for target_text, backup_path in reversed(restore_plan):
                restore_target(Path(target_text), backup_path)
            return 1
    finally:
        active_stack.remove(pack_id)


def main() -> int:
    args = parse_args()
    return install_pack(
        pack_path=args.pack,
        dry_run=args.dry_run,
        no_verify=args.no_verify,
        installed_this_run=set(),
        active_stack=set(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
