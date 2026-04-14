from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser().resolve()
STATE_DIR = CODEX / "state"


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


PACKS_ROOT = CODEX / "packs"
INSTALLED_PACKS_PATH = STATE_DIR / "installed-packs.json"
PACK_BACKUP_ROOT = STATE_DIR / "backups" / "packs"


@dataclass(frozen=True)
class PackTarget:
    source: Path
    target: Path
    raw_from: str
    raw_to: str


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def expand_user_path(path_text: str) -> Path:
    if path_text.startswith("~/"):
        return HOME / path_text[2:]
    return Path(path_text).expanduser()


def pack_root_from_input(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if path.is_file() and path.name == "pack.json":
        return path.parent
    return path


def load_pack(pack_path: str) -> tuple[Path, dict[str, Any]]:
    pack_root = pack_root_from_input(pack_path)
    manifest_path = pack_root / "pack.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"pack.json not found under {pack_root}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return pack_root, payload


def pack_manifest_id(manifest: dict[str, Any], pack_root: Path) -> str:
    return str(manifest.get("id") or pack_root.name)


def find_pack_by_id(pack_id: str) -> Path | None:
    if not PACKS_ROOT.exists():
        return None
    normalized = pack_id.strip()
    direct = PACKS_ROOT / normalized
    if (direct / "pack.json").exists():
        return direct.resolve()
    for manifest_path in PACKS_ROOT.glob("*/pack.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if pack_manifest_id(payload, manifest_path.parent) == normalized:
            return manifest_path.parent.resolve()
    return None


def resolve_dependency_path(current_pack_root: Path, dependency: str) -> Path:
    dep = dependency.strip()
    if not dep:
        raise FileNotFoundError("empty dependency value")
    looks_like_path = (
        dep.startswith(".")
        or dep.startswith("/")
        or dep.startswith("~/")
        or "/" in dep
        or dep.endswith(".json")
    )
    if looks_like_path:
        candidate = Path(dep).expanduser()
        if not candidate.is_absolute():
            candidate = (current_pack_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.is_file() and candidate.name == "pack.json":
            return candidate.parent
        if (candidate / "pack.json").exists():
            return candidate
        raise FileNotFoundError(f"dependency pack not found: {dependency}")
    resolved = find_pack_by_id(dep)
    if resolved is None:
        raise FileNotFoundError(f"dependency pack id not found: {dependency}")
    return resolved


def pack_targets(pack_root: Path, manifest: dict[str, Any]) -> list[PackTarget]:
    targets: list[PackTarget] = []
    for item in manifest.get("targets", []):
        raw_from = str(item.get("from") or "").strip()
        raw_to = str(item.get("to") or "").strip()
        if not raw_from or not raw_to:
            continue
        source = (pack_root / raw_from).resolve()
        target = expand_user_path(raw_to).resolve()
        targets.append(
            PackTarget(
                source=source,
                target=target,
                raw_from=raw_from,
                raw_to=raw_to,
            )
        )
    return targets


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def path_snapshot(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        return f"dir:{sum(1 for _ in path.rglob('*'))}"
    return f"file:{path.stat().st_size}"


def backup_target(target: Path, backup_root: Path) -> Path | None:
    if not target.exists():
        return None
    if str(target).startswith(str(HOME)):
        destination = backup_root / target.relative_to(HOME)
    else:
        destination = backup_root / target.name
    ensure_parent(destination)
    if target.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(target, destination)
    else:
        shutil.copy2(target, destination)
    return destination


def remove_target_path(target: Path) -> None:
    if not target.exists():
        return
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def restore_target(target: Path, backup_path: Path | None) -> None:
    remove_target_path(target)
    if backup_path is None:
        return
    ensure_parent(target)
    if backup_path.is_dir():
        shutil.copytree(backup_path, target)
    else:
        shutil.copy2(backup_path, target)


def install_target(target: PackTarget) -> None:
    if not target.source.exists():
        raise FileNotFoundError(f"pack source missing: {target.source}")
    ensure_parent(target.target)
    if target.source.is_dir():
        if target.target.exists():
            shutil.rmtree(target.target)
        shutil.copytree(target.source, target.target)
    else:
        shutil.copy2(target.source, target.target)


def load_installed_packs() -> list[dict[str, Any]]:
    if not INSTALLED_PACKS_PATH.exists():
        return []
    return json.loads(INSTALLED_PACKS_PATH.read_text(encoding="utf-8"))


def save_installed_packs(payload: list[dict[str, Any]]) -> None:
    ensure_state_dir()
    INSTALLED_PACKS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register_install(record: dict[str, Any]) -> None:
    installs = [item for item in load_installed_packs() if item.get("id") != record.get("id")]
    installs.append(record)
    installs.sort(key=lambda item: (str(item.get("installed_at") or ""), str(item.get("id") or "")))
    save_installed_packs(installs)


def command_template_context(pack_root: Path) -> dict[str, str]:
    return {
        "PACK_ROOT": str(pack_root),
        "CODEX_HOME": str(CODEX),
        "HOME": str(HOME),
        "PYTHON": sys.executable,
    }


def substitute_command(command: str, context: dict[str, str]) -> str:
    result = command
    for key, value in context.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def run_verify_commands(
    *,
    pack_root: Path,
    manifest: dict[str, Any],
    yield_output: bool = True,
) -> list[dict[str, Any]]:
    context = command_template_context(pack_root)
    results: list[dict[str, Any]] = []
    for raw_command in manifest.get("verify", []):
        command = substitute_command(str(raw_command), context)
        completed = subprocess.run(
            shlex.split(command),
            cwd=str(pack_root),
            text=True,
            capture_output=True,
            check=False,
        )
        result = {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        results.append(result)
        if yield_output:
            print(f"$ {command}")
            if completed.stdout.strip():
                print(completed.stdout.rstrip())
            if completed.stderr.strip():
                print(completed.stderr.rstrip())
        if completed.returncode != 0:
            break
    return results
