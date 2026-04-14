from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import CODEX, discover_project_docs
from recall_query import build_payload_for_query


GENERATED_DIR = CODEX / "generated" / "theory-loops"
INDEX_PATH = GENERATED_DIR / "index.json"
ROOT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
)

PLACEHOLDER_JUDGE = "- [ ] Add one observable outcome that proves the task is done."
PLACEHOLDER_OBSERVATION = "- [ ] Add the strongest concrete observation from code, logs, tests, or runtime behavior."
PLACEHOLDER_HYPOTHESIS = "- [ ] State at least one hypothesis and how you will falsify it."
PLACEHOLDER_ASSUMPTION = "- [ ] Record any assumption that still needs proof."
PLACEHOLDER_BOUNDARY = "- [ ] State what is out of scope or must remain unchanged."
PLACEHOLDER_PROBE = "- [ ] Add the next probe that will reduce uncertainty fastest."
PLACEHOLDER_VERIFY = "- [ ] Add the concrete command or manual check that will validate the outcome."


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str, *, fallback: str = "task") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold and validate explicit theory-building notes for engineering work.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Create a theory-loop note for the current task.")
    start.add_argument("task", help="Task statement or problem to solve.")
    start.add_argument("--cwd", default=".", help="Working directory for the task.")
    start.add_argument("--output", default="", help="Optional explicit output path.")
    start.add_argument("--judge", action="append", default=[], help="Observable success criterion.")
    start.add_argument("--observation", action="append", default=[], help="Concrete observation already known.")
    start.add_argument("--hypothesis", action="append", default=[], help="Hypothesis to test.")
    start.add_argument("--assumption", action="append", default=[], help="Assumption that still needs proof.")
    start.add_argument("--boundary", action="append", default=[], help="Boundary or non-goal.")
    start.add_argument("--probe", action="append", default=[], help="Next investigative step.")
    start.add_argument("--verify", action="append", default=[], help="Verification command or check.")
    start.add_argument("--limit", type=int, default=8, help="Maximum recall results to preload.")

    check = subparsers.add_parser("check", help="Validate that a theory-loop note has the required sections filled.")
    check.add_argument("path", nargs="?", default="", help="Path to a specific theory-loop note.")
    check.add_argument("--cwd", default=".", help="Working directory used to locate the latest note.")
    check.add_argument("--latest", action="store_true", help="Validate the latest note matching the cwd/project.")
    check.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    listing = subparsers.add_parser("list", help="List recent theory-loop notes.")
    listing.add_argument("--cwd", default="", help="Filter by working directory or project.")
    listing.add_argument("--project", default="", help="Filter by explicit project root.")
    listing.add_argument("--limit", type=int, default=10, help="Maximum notes to display.")
    listing.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def ensure_generated_dir() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def load_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def save_index(entries: list[dict[str, Any]]) -> None:
    ensure_generated_dir()
    INDEX_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_path_text(path_text: str) -> str:
    return str(Path(path_text).expanduser().resolve())


def resolve_cwd(cwd: str) -> Path:
    return Path(cwd).expanduser().resolve()


def find_project_root(cwd: Path) -> Path:
    current = cwd
    while True:
        if any((current / marker).exists() for marker in ROOT_MARKERS):
            return current
        if current.parent == current:
            return cwd
        current = current.parent


def collect_markers(project_root: Path) -> list[str]:
    markers: list[str] = []
    for marker in ROOT_MARKERS:
        if (project_root / marker).exists():
            markers.append(marker)
    return markers


def run_command(argv: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def collect_git_facts(project_root: Path) -> dict[str, Any]:
    top_level = run_command(["git", "rev-parse", "--show-toplevel"], cwd=project_root)
    if not top_level:
        return {}
    branch = run_command(["git", "branch", "--show-current"], cwd=project_root) or "(detached)"
    status_text = run_command(["git", "status", "--short"], cwd=project_root)
    status_lines = [line for line in status_text.splitlines() if line.strip()]
    return {
        "top_level": top_level,
        "branch": branch,
        "status_lines": status_lines[:12],
    }


def detect_package_manager(project_root: Path) -> str:
    if (project_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_root / "yarn.lock").exists():
        return "yarn"
    if (project_root / "bun.lockb").exists() or (project_root / "bun.lock").exists():
        return "bun"
    return "npm"


def package_script_commands(project_root: Path) -> list[str]:
    package_json = project_root / "package.json"
    if not package_json.exists():
        return []
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return []
    package_manager = detect_package_manager(project_root)
    commands: list[str] = []
    for name in ("test", "build", "lint", "typecheck", "check"):
        if name in scripts:
            commands.append(f"{package_manager} run {name}")
    return commands


def makefile_commands(project_root: Path) -> list[str]:
    makefile = project_root / "Makefile"
    if not makefile.exists():
        return []
    text = makefile.read_text(encoding="utf-8", errors="ignore")
    commands: list[str] = []
    for target in ("test", "build", "lint", "check"):
        if re.search(rf"(?m)^{re.escape(target)}\s*:", text):
            commands.append(f"make {target}")
    return commands


def python_commands(project_root: Path) -> list[str]:
    commands: list[str] = []
    if (project_root / "pyproject.toml").exists() or (project_root / "pytest.ini").exists() or (project_root / "tests").exists():
        commands.append("uv run pytest")
    return commands


def candidate_validation_commands(project_root: Path) -> list[str]:
    commands: list[str] = []
    commands.extend(package_script_commands(project_root))
    commands.extend(makefile_commands(project_root))
    commands.extend(python_commands(project_root))
    if (project_root / "Cargo.toml").exists():
        commands.append("cargo test")
    if (project_root / "go.mod").exists():
        commands.append("go test ./...")
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped[:8]


def collect_recall(task: str, project_root: Path, limit: int) -> dict[str, Any]:
    try:
        return build_payload_for_query(query=task, project=str(project_root), limit=limit)
    except Exception:
        return {
            "preload": {
                "top_conversations": [],
                "top_memories": [],
                "top_skills": [],
                "project_docs": discover_project_docs(str(project_root)),
            }
        }


def bullet_lines(items: list[str], placeholder: str) -> list[str]:
    if not items:
        return [placeholder]
    return [f"- {item}" for item in items]


def build_probe_items(
    *,
    project_docs: list[str],
    git_facts: dict[str, Any],
    recall_payload: dict[str, Any],
    validation_commands: list[str],
    extra_items: list[str],
) -> list[str]:
    items: list[str] = []
    if project_docs:
        items.append(f"Read the highest-signal project doc first: `{project_docs[0]}`")
    status_lines = git_facts.get("status_lines", [])
    if status_lines:
        items.append(f"Inspect the most relevant dirty path from git status: `{status_lines[0]}`")
    top_memories = recall_payload.get("preload", {}).get("top_memories", [])
    if top_memories:
        top_memory = top_memories[0]
        items.append(f"Open the top recalled memory: `{top_memory.get('title', '-')}`")
    if validation_commands:
        items.append(f"Choose the primary verification command now: `{validation_commands[0]}`")
    items.extend(extra_items)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def render_note(
    *,
    note_id: str,
    task: str,
    cwd: Path,
    project_root: Path,
    created_at: str,
    markers: list[str],
    git_facts: dict[str, Any],
    recall_payload: dict[str, Any],
    validation_commands: list[str],
    judge_items: list[str],
    observation_items: list[str],
    hypothesis_items: list[str],
    assumption_items: list[str],
    boundary_items: list[str],
    probe_items: list[str],
    verify_items: list[str],
) -> str:
    lines: list[str] = [
        f"# Theory Loop: {task}",
        "",
        f"- Theory loop id: `{note_id}`",
        f"- Created: `{created_at}`",
        f"- CWD: `{cwd}`",
        f"- Project root: `{project_root}`",
        "",
        "## Success Judge",
        "",
    ]
    lines.extend(bullet_lines(judge_items, PLACEHOLDER_JUDGE))
    lines.extend(
        [
            "",
            "## Current Evidence",
            "",
            f"- Project markers: `{', '.join(markers) if markers else '-'}`",
        ]
    )
    if git_facts:
        lines.append(f"- Git branch: `{git_facts.get('branch', '-')}`")
        for status_line in git_facts.get("status_lines", []):
            lines.append(f"- Git status: `{status_line}`")
    else:
        lines.append("- Git branch: `-`")

    project_docs = recall_payload.get("preload", {}).get("project_docs", [])
    if not project_docs:
        project_docs = discover_project_docs(str(project_root))
    if project_docs:
        for doc in project_docs[:6]:
            lines.append(f"- Project doc: `{doc}`")

    for record in recall_payload.get("preload", {}).get("top_memories", [])[:4]:
        lines.append(f"- Recall memory: `{record.get('title', '-')}` -> `{record.get('path') or '-'}`")
    for record in recall_payload.get("preload", {}).get("top_skills", [])[:4]:
        lines.append(f"- Recall skill: `{record.get('title', '-')}` -> `{record.get('path') or '-'}`")
    for record in recall_payload.get("preload", {}).get("top_conversations", [])[:3]:
        lines.append(f"- Recall conversation: `{record.get('title', '-')}` -> `{record.get('path') or '-'}`")
    for command in validation_commands:
        lines.append(f"- Candidate command: `{command}`")

    lines.extend(
        [
            "",
            "## Working Theory",
            "",
            "### Observations",
            "",
        ]
    )
    lines.extend(bullet_lines(observation_items, PLACEHOLDER_OBSERVATION))
    lines.extend(
        [
            "",
            "### Hypotheses",
            "",
        ]
    )
    lines.extend(bullet_lines(hypothesis_items, PLACEHOLDER_HYPOTHESIS))
    lines.extend(
        [
            "",
            "### Assumptions",
            "",
        ]
    )
    lines.extend(bullet_lines(assumption_items, PLACEHOLDER_ASSUMPTION))
    lines.extend(
        [
            "",
            "### Boundaries / Non-goals",
            "",
        ]
    )
    lines.extend(bullet_lines(boundary_items, PLACEHOLDER_BOUNDARY))
    lines.extend(
        [
            "",
            "## Probe Plan",
            "",
        ]
    )
    lines.extend(bullet_lines(probe_items, PLACEHOLDER_PROBE))
    lines.extend(
        [
            "",
            "## Verification",
            "",
        ]
    )
    lines.extend(bullet_lines(verify_items, PLACEHOLDER_VERIFY))
    lines.extend(
        [
            "",
            "## Decision Log",
            "",
            f"- {created_at} Created the theory loop and preloaded current evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def register_entry(entry: dict[str, Any]) -> None:
    entries = load_index()
    replaced = False
    for index, existing in enumerate(entries):
        if existing.get("id") == entry["id"]:
            entries[index] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    entries.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    save_index(entries)


def start_command(args: argparse.Namespace) -> int:
    cwd = resolve_cwd(args.cwd)
    project_root = find_project_root(cwd)
    created_at = now_utc_iso()
    note_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{slugify(project_root.name, fallback='project')}-{slugify(args.task)}"
    markers = collect_markers(project_root)
    git_facts = collect_git_facts(project_root)
    recall_payload = collect_recall(args.task, project_root, args.limit)
    validation_commands = candidate_validation_commands(project_root)
    project_docs = recall_payload.get("preload", {}).get("project_docs", [])
    probe_items = build_probe_items(
        project_docs=project_docs,
        git_facts=git_facts,
        recall_payload=recall_payload,
        validation_commands=validation_commands,
        extra_items=args.probe,
    )

    output_path = Path(args.output).expanduser() if args.output else GENERATED_DIR / f"{note_id}.md"
    output_path = output_path.resolve()
    ensure_generated_dir()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    note_text = render_note(
        note_id=note_id,
        task=args.task,
        cwd=cwd,
        project_root=project_root,
        created_at=created_at,
        markers=markers,
        git_facts=git_facts,
        recall_payload=recall_payload,
        validation_commands=validation_commands,
        judge_items=args.judge,
        observation_items=args.observation,
        hypothesis_items=args.hypothesis,
        assumption_items=args.assumption,
        boundary_items=args.boundary,
        probe_items=probe_items,
        verify_items=args.verify,
    )
    output_path.write_text(note_text, encoding="utf-8")

    entry = {
        "id": note_id,
        "task": args.task,
        "created_at": created_at,
        "cwd": str(cwd),
        "project_root": str(project_root),
        "note_path": str(output_path),
        "validated": False,
        "checked_at": None,
    }
    register_entry(entry)

    print(f"theory note: {output_path}")
    print(f"project root: {project_root}")
    print(f"preload summary: docs={len(project_docs)} memories={len(recall_payload.get('preload', {}).get('top_memories', []))} skills={len(recall_payload.get('preload', {}).get('top_skills', []))} commands={len(validation_commands)}")
    return 0


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^#{2,3}\s+(.*)$", line.strip())
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line.rstrip())
    return sections


def has_meaningful_bullet(lines: list[str], placeholders: set[str]) -> bool:
    for raw in lines:
        stripped = raw.strip()
        if not stripped.startswith("- "):
            continue
        if stripped in placeholders:
            continue
        if stripped == "- none":
            continue
        return True
    return False


def latest_entry_for_project(project: str | None) -> dict[str, Any] | None:
    if not project:
        return None
    normalized = normalize_path_text(project)
    for entry in load_index():
        note_path = str(entry.get("note_path") or "")
        if not note_path:
            continue
        entry_project = str(entry.get("project_root") or "")
        entry_cwd = str(entry.get("cwd") or "")
        if entry_project == normalized:
            return entry
        if normalized.startswith(entry_project) or entry_project.startswith(normalized):
            return entry
        if entry_cwd == normalized:
            return entry
    return None


def resolve_note_path(path_text: str, *, cwd_text: str, latest: bool) -> Path:
    if path_text:
        return Path(path_text).expanduser().resolve()
    if latest or cwd_text:
        cwd = resolve_cwd(cwd_text)
        entry = latest_entry_for_project(str(find_project_root(cwd))) or latest_entry_for_project(str(cwd))
        if entry and entry.get("note_path"):
            return Path(str(entry["note_path"])).expanduser().resolve()
    raise SystemExit("No theory-loop note found. Pass a path or create a note with `theory-loop start` first.")


def update_validation_status(note_path: Path, *, ok: bool) -> None:
    entries = load_index()
    changed = False
    for entry in entries:
        if str(note_path) != str(entry.get("note_path")):
            continue
        entry["validated"] = ok
        entry["checked_at"] = now_utc_iso()
        changed = True
        break
    if changed:
        save_index(entries)


def check_command(args: argparse.Namespace) -> int:
    note_path = resolve_note_path(args.path, cwd_text=args.cwd, latest=args.latest)
    text = note_path.read_text(encoding="utf-8")
    sections = parse_sections(text)
    required = {
        "Success Judge": {PLACEHOLDER_JUDGE},
        "Hypotheses": {PLACEHOLDER_HYPOTHESIS},
        "Boundaries / Non-goals": {PLACEHOLDER_BOUNDARY},
        "Verification": {PLACEHOLDER_VERIFY},
    }
    missing: list[str] = []
    for title, placeholders in required.items():
        if not has_meaningful_bullet(sections.get(title, []), placeholders):
            missing.append(title)

    ok = not missing
    update_validation_status(note_path, ok=ok)
    curation_summary: dict[str, Any] | None = None
    curation_error = ""
    quiet_context_summary: dict[str, Any] | None = None
    quiet_context_error = ""
    if ok:
        try:
            from curation_queue import refresh_curation_artifacts

            curation_summary = refresh_curation_artifacts()
        except Exception as exc:
            curation_error = str(exc)
        if curation_summary is not None:
            try:
                from quiet_context import refresh_quiet_context

                quiet_context_summary = refresh_quiet_context()
            except Exception as exc:
                quiet_context_error = str(exc)

    payload = {
        "ok": ok,
        "path": str(note_path),
        "missing": missing,
    }
    if curation_summary is not None:
        payload["curation"] = {
            "queue_path": curation_summary["queue_path"],
            "count": curation_summary["count"],
            "procedure_candidate_count": curation_summary["procedure_candidate_count"],
    }
    if curation_error:
        payload["curation_error"] = curation_error
    if quiet_context_summary is not None:
        payload["quiet_context"] = {
            "daily_brief": quiet_context_summary["daily_brief"],
            "focus_count": quiet_context_summary["focus_count"],
            "hot_context_generated_at": quiet_context_summary["hot_context_generated_at"],
        }
    if quiet_context_error:
        payload["quiet_context_error"] = quiet_context_error
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if ok:
            print(f"PASS {note_path}")
            print("required sections satisfied: Success Judge, Hypotheses, Boundaries / Non-goals, Verification")
            if curation_summary is not None:
                print(
                    "curation refreshed: "
                    f"entries={curation_summary['count']} "
                    f"procedures={curation_summary['procedure_candidate_count']}"
                )
            elif curation_error:
                print(f"curation refresh skipped: {curation_error}")
            if quiet_context_summary is not None:
                print(
                    "quiet context refreshed: "
                    f"focus_briefs={quiet_context_summary['focus_count']} "
                    f"hot_context={quiet_context_summary['hot_context_generated_at'] or '-'}"
                )
            elif quiet_context_error:
                print(f"quiet context refresh skipped: {quiet_context_error}")
        else:
            print(f"FAIL {note_path}")
            print(f"missing sections: {', '.join(missing)}")
    return 0 if ok else 1


def matching_entries(*, cwd: str = "", project: str = "") -> list[dict[str, Any]]:
    normalized_cwd = normalize_path_text(cwd) if cwd else ""
    normalized_project = normalize_path_text(project) if project else ""
    entries = load_index()
    if not normalized_cwd and not normalized_project:
        return entries

    matched: list[dict[str, Any]] = []
    for entry in entries:
        entry_project = str(entry.get("project_root") or "")
        entry_cwd = str(entry.get("cwd") or "")
        if normalized_project:
            if entry_project == normalized_project or normalized_project.startswith(entry_project) or entry_project.startswith(normalized_project):
                matched.append(entry)
                continue
        if normalized_cwd:
            if entry_cwd == normalized_cwd or normalized_cwd.startswith(entry_project) or entry_project.startswith(normalized_cwd):
                matched.append(entry)
    return matched


def list_command(args: argparse.Namespace) -> int:
    entries = matching_entries(cwd=args.cwd, project=args.project)[: max(args.limit, 1)]
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("no theory-loop notes found")
        return 0
    for entry in entries:
        print(
            f"- {entry.get('created_at', '-')} validated={entry.get('validated', False)} task={entry.get('task', '-')}"
        )
        print(f"  project: {entry.get('project_root', '-')}")
        print(f"  path: {entry.get('note_path', '-')}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "start":
        return start_command(args)
    if args.command == "check":
        return check_command(args)
    if args.command == "list":
        return list_command(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
