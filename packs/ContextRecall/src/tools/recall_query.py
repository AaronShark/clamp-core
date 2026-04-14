from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import (
    connect_db,
    default_project_for_cwd,
    discover_project_docs,
    epoch_to_ms,
    load_manifest,
    load_records,
    rank_records,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the local recall index.")
    parser.add_argument("query", nargs="?", default="", help="Free-text recall query.")
    parser.add_argument("--topic", default="", help="Explicit topic query.")
    parser.add_argument("--project", default="", help="Project path to bias recall and list docs from.")
    parser.add_argument(
        "--kind",
        action="append",
        choices=["conversation", "memory", "skill"],
        help="Limit results to one or more record kinds.",
    )
    parser.add_argument("--limit", type=int, default=12, help="Maximum results to return.")
    parser.add_argument(
        "--format",
        choices=["text", "json", "preload"],
        default="text",
        help="Output format. 'preload' groups results for task startup.",
    )
    return parser.parse_args()


def iso_from_epoch_ms(value: int) -> str:
    if not value:
        return "-"
    normalized = epoch_to_ms(value)
    return datetime.fromtimestamp(normalized / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def choose_query(args: argparse.Namespace) -> str:
    explicit = args.topic.strip()
    if explicit:
        return explicit
    return args.query.strip()


def choose_project(args: argparse.Namespace) -> str | None:
    explicit = args.project.strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    if choose_query(args):
        return None
    return default_project_for_cwd(str(Path.cwd()))


def build_payload_for_query(
    *,
    query: str = "",
    project: str | None = None,
    kinds: set[str] | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    manifest = load_manifest()

    conn = connect_db()
    try:
        records = load_records(conn)
    finally:
        conn.close()

    selected_kinds = set(kinds or [])
    ranked = rank_records(
        records,
        query=query,
        project=project,
        kinds=selected_kinds,
        limit=max(limit, 1),
    )

    preload_conversations = rank_records(
        records,
        query=query,
        project=project,
        kinds={"conversation"} if not selected_kinds or "conversation" in selected_kinds else set(),
        limit=3,
    )
    preload_memories = rank_records(
        records,
        query=query,
        project=project,
        kinds={"memory"} if not selected_kinds or "memory" in selected_kinds else set(),
        limit=5,
    )
    preload_skills = rank_records(
        records,
        query=query,
        project=project,
        kinds={"skill"} if not selected_kinds or "skill" in selected_kinds else set(),
        limit=4,
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in ranked:
        grouped[record["kind"]].append(record)

    project_docs = discover_project_docs(project)

    return {
        "query": query,
        "project": project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest,
        "counts": {
            "total_matches": len(ranked),
            "conversations": len(grouped.get("conversation", [])),
            "memories": len(grouped.get("memory", [])),
            "skills": len(grouped.get("skill", [])),
        },
        "results": ranked,
        "preload": {
            "top_conversations": preload_conversations,
            "top_memories": preload_memories,
            "top_skills": preload_skills,
            "project_docs": project_docs,
        },
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    return build_payload_for_query(
        query=choose_query(args),
        project=choose_project(args),
        kinds=set(args.kind or []),
        limit=args.limit,
    )


def render_result_line(record: dict[str, Any]) -> list[str]:
    metadata = record["metadata"]
    lines = [
        f"- [{record['kind']}] {record['title']}  score={record['score']}",
        f"  path: {record['path'] or '-'}",
        f"  updated: {iso_from_epoch_ms(int(record['updated_ts'] or 0))}",
        f"  summary: {record['summary']}",
    ]
    if record["kind"] == "conversation":
        thread = metadata.get("thread_name") or "-"
        themes = ", ".join(metadata.get("themes", [])[:3]) or "-"
        lines.append(f"  thread: {thread}")
        lines.append(f"  themes: {themes}")
    if record["kind"] == "memory":
        topic = metadata.get("topic") or "-"
        related = ", ".join(metadata.get("related_skills", [])[:4]) or "-"
        lines.append(f"  topic: {topic}")
        lines.append(f"  related_skills: {related}")
    if record["kind"] == "skill":
        root = metadata.get("skill_root") or "-"
        domain = metadata.get("domain") or "-"
        lines.append(f"  root: {root}")
        lines.append(f"  domain: {domain}")
    return lines


def render_text(payload: dict[str, Any], *, preload: bool) -> str:
    query = payload["query"] or "(project recall)"
    lines = [
        f"=== RECALL: {query} ===",
        f"matches: {payload['counts']['total_matches']}",
    ]
    if payload["project"]:
        lines.append(f"project: {payload['project']}")
    manifest_counts = payload.get("manifest", {}).get("counts")
    if manifest_counts:
        lines.append(
            "index: "
            f"sessions={manifest_counts.get('session', 0)} "
            f"memories={manifest_counts.get('memory', 0)} "
            f"skills={manifest_counts.get('skill', 0)}"
        )
    lines.append("")

    if preload:
        sections = [
            ("Top Conversations", payload["preload"]["top_conversations"]),
            ("Top Memories", payload["preload"]["top_memories"]),
            ("Relevant Skills", payload["preload"]["top_skills"]),
        ]
        for title, items in sections:
            lines.append(f"{title}:")
            if not items:
                lines.append("- none")
            else:
                for record in items:
                    lines.extend(render_result_line(record))
            lines.append("")
        lines.append("Project Docs:")
        if not payload["preload"]["project_docs"]:
            lines.append("- none")
        else:
            for doc in payload["preload"]["project_docs"]:
                lines.append(f"- {doc}")
        return "\n".join(lines)

    if not payload["results"]:
        lines.append("No matches found.")
        return "\n".join(lines)

    for record in payload["results"]:
        lines.extend(render_result_line(record))
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "preload":
        print(render_text(payload, preload=True))
    else:
        print(render_text(payload, preload=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
