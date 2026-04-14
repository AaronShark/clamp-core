from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import CODEX
from recall_query import build_payload_for_query
from retrospect_common import write_text_if_changed
from user_conclusions import ranked_user_conclusions, refresh_user_conclusions


AGENTS_PATH = CODEX / "AGENTS.md"
GENERATED_DIR = CODEX / "generated" / "hot-context"
SYSTEM_HOT_PATH = GENERATED_DIR / "system-hot.md"
USER_HOT_PATH = GENERATED_DIR / "user-hot.md"
PROJECT_HOT_DIR = GENERATED_DIR / "project-hot"
HOT_CONTEXT_MANIFEST_PATH = GENERATED_DIR / "manifest.json"

SYSTEM_TOKEN_BUDGET = 350
USER_TOKEN_BUDGET = 500
PROJECT_TOKEN_BUDGET = 700

SYSTEM_SECTION_PRIORITIES = (
    "Shared Python Environment",
    "Collaboration Defaults",
    "Durable Memory",
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str, *, fallback: str = "project") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or fallback


def project_slug(project_path: str) -> str:
    normalized = str(Path(project_path).expanduser().resolve())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(Path(normalized).name)}-{digest}"


def load_hot_context_manifest() -> dict[str, Any]:
    if not HOT_CONTEXT_MANIFEST_PATH.exists():
        return {}
    try:
        payload = json.loads(HOT_CONTEXT_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        match = re.match(r"^##\s+(.*)$", stripped)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line.rstrip())
    return sections


def extract_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        bullet = stripped[2:].strip()
        if bullet:
            bullets.append(bullet)
    return bullets


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def trim_items_to_budget(items: list[str], budget: int) -> list[str]:
    kept: list[str] = []
    used = 0
    for item in items:
        item_cost = approx_tokens(item)
        if kept and used + item_cost > budget:
            break
        if not kept and item_cost > budget:
            kept.append(item)
            break
        kept.append(item)
        used += item_cost
    return kept


def render_hot_markdown(
    *,
    title: str,
    generated_at: str,
    token_budget: int,
    items: list[str],
    notes: list[str] | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated_at}`",
        f"- Token budget: `{token_budget}`",
        f"- Estimated tokens used: `{sum(approx_tokens(item) for item in items)}`",
        "",
    ]
    if notes:
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append("## Active Context")
    lines.append("")
    if not items:
        lines.extend(["- none", ""])
    else:
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


def build_system_items() -> list[str]:
    if not AGENTS_PATH.exists():
        return []
    sections = parse_sections(AGENTS_PATH.read_text(encoding="utf-8"))
    items: list[str] = []
    for section_name in SYSTEM_SECTION_PRIORITIES:
        items.extend(extract_bullets(sections.get(section_name, [])))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return trim_items_to_budget(deduped, SYSTEM_TOKEN_BUDGET)


def build_user_items(project: str | None = None) -> list[str]:
    refresh_user_conclusions()
    items = [entry["conclusion"] for entry in ranked_user_conclusions(project=project, limit=24)]
    return trim_items_to_budget(items, USER_TOKEN_BUDGET)


def project_memory_items(query: str, project: str) -> tuple[list[str], dict[str, Any]]:
    payload = build_payload_for_query(query=query, project=project, limit=8)
    items: list[str] = []

    for record in payload["preload"]["top_memories"][:3]:
        items.append(f"Memory: {record['title']} -> {record['summary']}")
    for record in payload["preload"]["top_skills"][:2]:
        items.append(f"Skill: {record['title']} -> {record['summary']}")
    for record in payload["preload"]["top_conversations"][:2]:
        items.append(f"Prior conversation: {record['title']} -> {record['summary']}")
    for doc in payload["preload"]["project_docs"][:4]:
        items.append(f"Project doc: {doc}")

    return trim_items_to_budget(items, PROJECT_TOKEN_BUDGET), payload


def build_project_payload(*, query: str = "", project: str | None = None) -> dict[str, Any] | None:
    if not project:
        return None
    project_path = str(Path(project).expanduser().resolve())
    items, payload = project_memory_items(query, project_path)
    slug = project_slug(project_path)
    project_path_md = PROJECT_HOT_DIR / f"{slug}.md"
    return {
        "slug": slug,
        "project": project_path,
        "path": str(project_path_md),
        "items": items,
        "payload": payload,
    }


def refresh_hot_context(
    *,
    query: str = "",
    project: str | None = None,
    persist_project_context: bool = False,
) -> dict[str, Any]:
    generated_at = now_utc_iso()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_HOT_DIR.mkdir(parents=True, exist_ok=True)

    system_items = build_system_items()
    user_items = build_user_items(project=project)
    project_payload = build_project_payload(query=query, project=project)

    write_text_if_changed(
        SYSTEM_HOT_PATH,
        render_hot_markdown(
            title="System Hot Context",
            generated_at=generated_at,
            token_budget=SYSTEM_TOKEN_BUDGET,
            items=system_items,
            notes=["Bounded always-on operating constraints projected from `AGENTS.md`."],
        ),
    )
    write_text_if_changed(
        USER_HOT_PATH,
        render_hot_markdown(
            title="User Hot Context",
            generated_at=generated_at,
            token_budget=USER_TOKEN_BUDGET,
            items=user_items,
            notes=["Evidence-backed user conclusions projected from `state/user-conclusions.jsonl`."],
        ),
    )

    project_summary: dict[str, Any] | None = None
    if project_payload is not None:
        project_path = Path(project_payload["path"])
        write_text_if_changed(
            project_path,
            render_hot_markdown(
                title=f"Project Hot Context: {Path(project_payload['project']).name}",
                generated_at=generated_at,
                token_budget=PROJECT_TOKEN_BUDGET,
                items=project_payload["items"],
                notes=[
                    "Bounded project context projected from recall results, project docs, and prior conversations."
                ],
            ),
        )
        project_summary = {
            "project": project_payload["project"],
            "slug": project_payload["slug"],
            "path": project_payload["path"],
            "items": project_payload["items"],
            "top_memories": [record["title"] for record in project_payload["payload"]["preload"]["top_memories"][:3]],
            "top_skills": [record["title"] for record in project_payload["payload"]["preload"]["top_skills"][:2]],
            "project_docs": project_payload["payload"]["preload"]["project_docs"][:4],
        }

    manifest = {
        "generated_at": generated_at,
        "query": query,
        "project": str(Path(project).expanduser().resolve()) if project else None,
        "system": {
            "path": str(SYSTEM_HOT_PATH),
            "token_budget": SYSTEM_TOKEN_BUDGET,
            "estimated_tokens": sum(approx_tokens(item) for item in system_items),
            "item_count": len(system_items),
            "items": system_items,
        },
        "user": {
            "path": str(USER_HOT_PATH),
            "token_budget": USER_TOKEN_BUDGET,
            "estimated_tokens": sum(approx_tokens(item) for item in user_items),
            "item_count": len(user_items),
            "items": user_items,
        },
        "project_context": project_summary,
    }
    persisted_manifest = dict(manifest)
    if not persist_project_context:
        persisted_manifest["query"] = ""
        persisted_manifest["project"] = None
        persisted_manifest["project_context"] = None
        persisted_manifest["scope"] = "global-runtime"
    else:
        persisted_manifest["scope"] = "project-runtime"
    write_text_if_changed(HOT_CONTEXT_MANIFEST_PATH, json.dumps(persisted_manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate bounded hot-context projections for Codex/CLAMP.")
    parser.add_argument("query", nargs="?", default="", help="Optional task query.")
    parser.add_argument("--topic", default="", help="Explicit topic override.")
    parser.add_argument("--project", default="", help="Optional project path.")
    return parser.parse_args()


def choose_query(args: argparse.Namespace) -> str:
    topic = args.topic.strip()
    if topic:
        return topic
    return args.query.strip()


def main() -> int:
    args = parse_args()
    query = choose_query(args)
    project = args.project.strip() or None
    manifest = refresh_hot_context(query=query, project=project)
    print(
        "hot context refreshed: "
        f"system_items={manifest['system']['item_count']} "
        f"user_items={manifest['user']['item_count']} "
        f"project={'yes' if manifest.get('project_context') else 'no'} "
        f"manifest={HOT_CONTEXT_MANIFEST_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
