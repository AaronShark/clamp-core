from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from hot_context import HOT_CONTEXT_MANIFEST_PATH, refresh_hot_context
from recall_common import CODEX, default_project_for_cwd
from recall_query import build_payload_for_query
from theory_loop import latest_entry_for_project


GENERATED_DIR = CODEX / "generated"
TASK_BRIEF_PATH = GENERATED_DIR / "task-brief.md"
PRELOAD_MANIFEST_PATH = GENERATED_DIR / "preload-manifest.json"
FOCUS_BRIEFS_DIR = GENERATED_DIR / "focus-briefs"
FOCUS_MANIFESTS_DIR = GENERATED_DIR / "focus-manifests"
DEFAULT_MAX_AGE_MINUTES = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build generated runtime context from the recall layer.")
    parser.add_argument("query", nargs="?", default="", help="Task query or topic.")
    parser.add_argument("--topic", default="", help="Explicit topic override.")
    parser.add_argument("--project", default="", help="Project path to preload context for.")
    parser.add_argument("--limit", type=int, default=12, help="Maximum ranked recall results.")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=DEFAULT_MAX_AGE_MINUTES,
        help="Maximum age for reusing an existing task brief before rebuilding it.",
    )
    parser.add_argument("--force", action="store_true", help="Force regeneration even if the current task brief is fresh.")
    return parser.parse_args()


def choose_query(args: argparse.Namespace) -> str:
    topic = args.topic.strip()
    if topic:
        return topic
    return args.query.strip()


def choose_project(args: argparse.Namespace, query: str) -> str | None:
    explicit = args.project.strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    if query:
        return None
    return default_project_for_cwd(str(Path.cwd()))


def render_section(title: str, items: list[dict], lines: list[str]) -> None:
    lines.extend([f"## {title}", ""])
    if not items:
        lines.extend(["- none", ""])
        return
    for item in items:
        lines.append(f"- {item['title']}")
        lines.append(f"  - kind: `{item['kind']}`")
        lines.append(f"  - path: `{item['path'] or '-'}`")
        lines.append(f"  - summary: {item['summary']}")
    lines.append("")


def render_hot_section(hot_context: dict, lines: list[str]) -> None:
    lines.extend(["## Hot Context", ""])

    system_items = hot_context.get("system", {}).get("items", [])
    user_items = hot_context.get("user", {}).get("items", [])
    project_context = hot_context.get("project_context")

    lines.append(f"- System hot: `{hot_context.get('system', {}).get('path', '-')}`")
    lines.append(f"- User hot: `{hot_context.get('user', {}).get('path', '-')}`")
    if project_context:
        lines.append(f"- Project hot: `{project_context.get('path', '-')}`")
    lines.append("")

    if system_items:
        lines.append("### System Hot")
        lines.append("")
        for item in system_items[:6]:
            lines.append(f"- {item}")
        lines.append("")

    if user_items:
        lines.append("### User Hot")
        lines.append("")
        for item in user_items[:8]:
            lines.append(f"- {item}")
        lines.append("")

    if project_context and project_context.get("items"):
        lines.append("### Project Hot")
        lines.append("")
        for item in project_context["items"][:8]:
            lines.append(f"- {item}")
        lines.append("")


def render_task_brief(payload: dict) -> str:
    latest_theory = latest_entry_for_project(payload.get("project"))
    lines: list[str] = [
        "# Task Brief",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Query: `{payload['query'] or '(project recall)'}`",
    ]
    if payload.get("project"):
        lines.append(f"- Project: `{payload['project']}`")
    lines.append("")

    render_hot_section(payload["hot_context"], lines)
    render_section("Top Memories", payload["preload"]["top_memories"], lines)
    render_section("Relevant Skills", payload["preload"]["top_skills"], lines)
    render_section("Top Conversations", payload["preload"]["top_conversations"], lines)

    lines.extend(["## Project Docs", ""])
    if not payload["preload"]["project_docs"]:
        lines.extend(["- none", ""])
    else:
        for doc in payload["preload"]["project_docs"]:
            lines.append(f"- `{doc}`")
        lines.append("")

    lines.extend(["## Latest Theory Loop", ""])
    if not latest_theory:
        lines.extend(["- none", ""])
    else:
        lines.append(f"- Task: {latest_theory.get('task', '-')}")
        lines.append(f"- Path: `{latest_theory.get('note_path', '-')}`")
        lines.append(f"- Validated: `{latest_theory.get('validated', False)}`")
        lines.append("")

    lines.extend(["## Working Notes", ""])
    if payload["preload"]["top_memories"]:
        lines.append("- Read the top memory first. It is the most likely canonical starting point.")
    if payload["preload"]["top_skills"]:
        lines.append("- Check whether one of the listed skills should be invoked before manual work.")
    if payload["preload"]["top_conversations"]:
        lines.append("- Review prior conversations for edge cases, failure modes, or project-specific history.")
    if payload["preload"]["project_docs"]:
        lines.append("- Open the listed project docs before making repo-local decisions.")
    if latest_theory:
        lines.append("- Reuse the latest theory loop if it still matches the current task; do not restart from zero unless the boundary changed.")
    lines.append("")
    return "\n".join(lines)


def slim_record(record: dict) -> dict:
    metadata = record.get("metadata", {})
    slim_metadata = {}
    if record["kind"] == "conversation":
        slim_metadata = {
            "thread_name": metadata.get("thread_name"),
            "themes": metadata.get("themes", []),
            "session_ref": metadata.get("session_ref"),
        }
    elif record["kind"] == "memory":
        slim_metadata = {
            "topic": metadata.get("topic"),
            "related_skills": metadata.get("related_skills", []),
            "artifact_type": metadata.get("artifact_type"),
        }
    elif record["kind"] == "skill":
        slim_metadata = {
            "skill_root": metadata.get("skill_root"),
            "domain": metadata.get("domain"),
        }
    return {
        "id": record["id"],
        "source": record["source"],
        "kind": record["kind"],
        "title": record["title"],
        "summary": record["summary"],
        "path": record["path"],
        "updated_ts": record["updated_ts"],
        "canonical": record["canonical"],
        "score": record["score"],
        "metadata": slim_metadata,
    }


def slim_payload(payload: dict) -> dict:
    latest_theory = latest_entry_for_project(payload.get("project"))
    return {
        "query": payload["query"],
        "project": payload["project"],
        "generated_at": payload["generated_at"],
        "manifest": payload["manifest"],
        "counts": payload["counts"],
        "hot_context": {
            "manifest_path": payload["hot_context"].get("manifest_path"),
            "system": payload["hot_context"].get("system"),
            "user": payload["hot_context"].get("user"),
            "project_context": payload["hot_context"].get("project_context"),
        },
        "latest_theory_loop": {
            "task": latest_theory.get("task", "-"),
            "note_path": latest_theory.get("note_path", "-"),
            "validated": bool(latest_theory.get("validated", False)),
        }
        if latest_theory
        else None,
        "preload": {
            "top_conversations": [slim_record(item) for item in payload["preload"]["top_conversations"]],
            "top_memories": [slim_record(item) for item in payload["preload"]["top_memories"]],
            "top_skills": [slim_record(item) for item in payload["preload"]["top_skills"]],
            "project_docs": payload["preload"]["project_docs"],
        },
    }


def build_context_payload(*, query: str = "", project: str | None = None, limit: int = 12) -> tuple[dict, dict]:
    hot_context = refresh_hot_context(query=query, project=project)
    payload = build_payload_for_query(query=query, project=project, limit=limit)
    payload["hot_context"] = {
        "manifest_path": str(HOT_CONTEXT_MANIFEST_PATH),
        **hot_context,
    }
    manifest_payload = slim_payload(payload)
    return payload, manifest_payload


def load_existing_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def manifest_needs_refresh(
    *,
    query: str,
    project: str | None,
    manifest_path: Path,
    max_age_minutes: int,
) -> bool:
    payload = load_existing_manifest(manifest_path)
    if not payload:
        return True

    if str(payload.get("query") or "") != query:
        return True
    if str(payload.get("project") or "") != str(project or ""):
        return True

    generated_at = str(payload.get("generated_at") or "").strip()
    if not generated_at:
        return True
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    age_seconds = (datetime.now(timezone.utc) - generated_dt).total_seconds()
    return age_seconds > max(60, max_age_minutes * 60)


def write_context_artifacts(
    *,
    query: str = "",
    project: str | None = None,
    limit: int = 12,
    brief_path: Path = TASK_BRIEF_PATH,
    manifest_path: Path = PRELOAD_MANIFEST_PATH,
) -> dict:
    payload, manifest_payload = build_context_payload(query=query, project=project, limit=limit)

    brief_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(render_task_brief(payload), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def ensure_context_artifacts(
    *,
    query: str = "",
    project: str | None = None,
    limit: int = 12,
    brief_path: Path = TASK_BRIEF_PATH,
    manifest_path: Path = PRELOAD_MANIFEST_PATH,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    force: bool = False,
) -> dict:
    if force or manifest_needs_refresh(
        query=query,
        project=project,
        manifest_path=manifest_path,
        max_age_minutes=max_age_minutes,
    ):
        payload = write_context_artifacts(
            query=query,
            project=project,
            limit=limit,
            brief_path=brief_path,
            manifest_path=manifest_path,
        )
        payload["_refreshed"] = True
        return payload

    payload = load_existing_manifest(manifest_path)
    payload["_refreshed"] = False
    return payload


def main() -> int:
    args = parse_args()
    query = choose_query(args)
    project = choose_project(args, query)
    payload = ensure_context_artifacts(
        query=query,
        project=project,
        limit=args.limit,
        max_age_minutes=args.max_age_minutes,
        force=args.force,
    )

    print(f"task brief: {TASK_BRIEF_PATH}")
    print(f"preload manifest: {PRELOAD_MANIFEST_PATH}")
    print(
        "preload summary: "
        f"conversations={len(payload['preload']['top_conversations'])} "
        f"memories={len(payload['preload']['top_memories'])} "
        f"skills={len(payload['preload']['top_skills'])} "
        f"project_docs={len(payload['preload']['project_docs'])} "
        f"refreshed={payload.get('_refreshed', False)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
