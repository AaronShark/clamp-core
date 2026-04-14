from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import CODEX, STATE_DIR, ensure_state_dir


USER_PROFILE_PATH = CODEX / "user-work-profile.md"
USER_CONCLUSIONS_PATH = STATE_DIR / "user-conclusions.jsonl"
PROFILE_SECTION_PRIORITY = (
    "Stable Collaboration Preferences",
    "Good Defaults For This User",
    "Snapshot",
    "Working Heuristic",
    "Long-Term Direction",
)
SECTION_CONFIDENCE = {
    "Stable Collaboration Preferences": "high",
    "Good Defaults For This User": "high",
    "Snapshot": "medium",
    "Working Heuristic": "medium",
    "Long-Term Direction": "medium",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        heading_match = re.match(r"^##\s+(.*)$", stripped)
        if heading_match:
            current = heading_match.group(1).strip()
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
        if not bullet:
            continue
        bullets.append(bullet)
    return bullets


def bootstrap_entries_from_profile() -> list[dict[str, Any]]:
    if not USER_PROFILE_PATH.exists():
        return []

    raw = USER_PROFILE_PATH.read_text(encoding="utf-8")
    sections = parse_sections(raw)
    refreshed_at = now_utc_iso()
    entries: list[dict[str, Any]] = []

    for section_name in PROFILE_SECTION_PRIORITY:
        for bullet in extract_bullets(sections.get(section_name, [])):
            entry_id = f"profile:{slugify(section_name)}:{slugify(bullet)[:60]}"
            entries.append(
                {
                    "id": entry_id,
                    "conclusion": bullet,
                    "scope": "global",
                    "confidence": SECTION_CONFIDENCE.get(section_name, "medium"),
                    "category": section_name,
                    "source": "user-work-profile",
                    "evidence_paths": [str(USER_PROFILE_PATH)],
                    "projection_targets": [
                        "generated/hot-context/user-hot.md",
                        str(USER_PROFILE_PATH),
                    ],
                    "status": "active",
                    "bootstrap": True,
                    "created_at": refreshed_at,
                    "updated_at": refreshed_at,
                    "last_reconfirmed_at": refreshed_at,
                }
            )
    return entries


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def write_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    ensure_state_dir()
    lines = [json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries]
    content = ("\n".join(lines) + "\n") if lines else ""
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == content:
        return
    path.write_text(content, encoding="utf-8")


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    normalized["id"] = str(normalized.get("id") or "").strip()
    normalized["conclusion"] = str(normalized.get("conclusion") or "").strip()
    normalized["scope"] = str(normalized.get("scope") or "global").strip()
    normalized["confidence"] = str(normalized.get("confidence") or "medium").strip()
    normalized["category"] = str(normalized.get("category") or "General").strip()
    normalized["source"] = str(normalized.get("source") or "manual").strip()
    normalized["status"] = str(normalized.get("status") or "active").strip()
    normalized["bootstrap"] = bool(normalized.get("bootstrap", False))
    normalized["evidence_paths"] = [str(path).strip() for path in normalized.get("evidence_paths", []) if str(path).strip()]
    normalized["projection_targets"] = [
        str(path).strip() for path in normalized.get("projection_targets", []) if str(path).strip()
    ]
    normalized["created_at"] = str(normalized.get("created_at") or now_utc_iso()).strip()
    normalized["updated_at"] = str(normalized.get("updated_at") or normalized["created_at"]).strip()
    normalized["last_reconfirmed_at"] = str(
        normalized.get("last_reconfirmed_at") or normalized["updated_at"]
    ).strip()
    return normalized


def merge_bootstrap_entry(existing: dict[str, Any] | None, bootstrap: dict[str, Any]) -> dict[str, Any]:
    merged = normalize_entry(bootstrap)
    if not existing:
        return merged

    previous = normalize_entry(existing)
    merged["created_at"] = previous.get("created_at") or merged["created_at"]
    stable_fields = (
        "conclusion",
        "scope",
        "confidence",
        "category",
        "source",
        "status",
        "evidence_paths",
        "projection_targets",
    )
    if all(previous.get(field) == merged.get(field) for field in stable_fields):
        merged["updated_at"] = previous.get("updated_at") or merged["updated_at"]
        merged["last_reconfirmed_at"] = (
            previous.get("last_reconfirmed_at")
            or previous.get("updated_at")
            or merged["last_reconfirmed_at"]
        )
    return merged


def merged_entries(existing: list[dict[str, Any]], bootstrap: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_bootstrap_by_id = {}
    bootstrap_by_id = {}
    for entry in existing:
        normalized = normalize_entry(entry)
        if not normalized.get("id") or not normalized.get("bootstrap"):
            continue
        existing_bootstrap_by_id[normalized["id"]] = normalized
    for entry in bootstrap:
        normalized = normalize_entry(entry)
        if not normalized.get("id"):
            continue
        bootstrap_by_id[normalized["id"]] = merge_bootstrap_entry(
            existing_bootstrap_by_id.get(normalized["id"]),
            normalized,
        )
    existing_by_id = {}
    for entry in existing:
        normalized = normalize_entry(entry)
        if not normalized.get("id"):
            continue
        if normalized.get("bootstrap"):
            continue
        existing_by_id[normalized["id"]] = normalized

    existing_by_id.update(bootstrap_by_id)

    ordered = list(existing_by_id.values())
    ordered.sort(
        key=lambda entry: (
            str(entry.get("category") or ""),
            str(entry.get("source") or ""),
            str(entry.get("conclusion") or ""),
        )
    )
    return ordered


def refresh_user_conclusions() -> dict[str, Any]:
    existing = load_jsonl(USER_CONCLUSIONS_PATH)
    bootstrap = bootstrap_entries_from_profile()
    merged = merged_entries(existing, bootstrap)
    write_jsonl(USER_CONCLUSIONS_PATH, merged)
    return {
        "path": str(USER_CONCLUSIONS_PATH),
        "count": len(merged),
        "active_count": sum(1 for entry in merged if entry.get("status") == "active"),
    }


def load_user_conclusions(*, active_only: bool = True) -> list[dict[str, Any]]:
    refresh_user_conclusions()
    entries = [normalize_entry(entry) for entry in load_jsonl(USER_CONCLUSIONS_PATH)]
    if active_only:
        entries = [entry for entry in entries if entry.get("status") == "active"]
    return entries


def confidence_rank(value: str) -> int:
    if value == "high":
        return 3
    if value == "medium":
        return 2
    return 1


def ranked_user_conclusions(*, project: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    entries = load_user_conclusions(active_only=True)

    def sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        scope = str(entry.get("scope") or "global")
        project_match = 0
        if project and scope.startswith("project:") and scope.split("project:", 1)[1] == project:
            project_match = 1
        return (
            project_match,
            confidence_rank(str(entry.get("confidence") or "medium")),
            str(entry.get("last_reconfirmed_at") or ""),
            str(entry.get("conclusion") or ""),
        )

    entries.sort(key=sort_key, reverse=True)
    return entries[: max(limit, 1)]


def add_manual_conclusion(
    *,
    conclusion: str,
    category: str = "Manual",
    confidence: str = "medium",
    scope: str = "global",
    evidence_path: str = "",
) -> dict[str, Any]:
    entries = load_jsonl(USER_CONCLUSIONS_PATH)
    created_at = now_utc_iso()
    evidence_paths = [evidence_path] if evidence_path else []
    entry = normalize_entry(
        {
            "id": f"manual:{slugify(conclusion)[:60]}:{slugify(created_at)[-12:]}",
            "conclusion": conclusion,
            "scope": scope,
            "confidence": confidence,
            "category": category,
            "source": "manual",
            "evidence_paths": evidence_paths,
            "projection_targets": [
                "generated/hot-context/user-hot.md",
                str(USER_PROFILE_PATH),
            ],
            "status": "active",
            "bootstrap": False,
            "created_at": created_at,
            "updated_at": created_at,
            "last_reconfirmed_at": created_at,
        }
    )
    entries.append(entry)
    write_jsonl(USER_CONCLUSIONS_PATH, merged_entries(entries, bootstrap_entries_from_profile()))
    return entry


def render_entries(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# User Conclusions",
        "",
        f"- Path: `{USER_CONCLUSIONS_PATH}`",
        f"- Entries: `{len(entries)}`",
        "",
    ]
    if not entries:
        lines.extend(["- none", ""])
        return "\n".join(lines)

    for entry in entries:
        lines.append(f"- [{entry['confidence']}] {entry['conclusion']}")
        lines.append(f"  - scope: `{entry['scope']}`")
        lines.append(f"  - category: `{entry['category']}`")
        lines.append(f"  - source: `{entry['source']}`")
        evidence = ", ".join(entry.get("evidence_paths", [])[:3]) or "-"
        lines.append(f"  - evidence: {evidence}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage evidence-backed user conclusions for hot-context projection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh", help="Refresh the conclusion ledger from the user profile.")
    list_parser = subparsers.add_parser("list", help="List active user conclusions.")
    list_parser.add_argument("--limit", type=int, default=12, help="Maximum entries to show.")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown-like text.")

    add_parser = subparsers.add_parser("add", help="Add a manual user conclusion.")
    add_parser.add_argument("conclusion", help="Conclusion text.")
    add_parser.add_argument("--category", default="Manual", help="Category label.")
    add_parser.add_argument("--confidence", default="medium", choices=["low", "medium", "high"])
    add_parser.add_argument("--scope", default="global", help="Scope label.")
    add_parser.add_argument("--evidence-path", default="", help="Optional evidence path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "refresh":
        summary = refresh_user_conclusions()
        print(
            f"user conclusions refreshed: count={summary['count']} active={summary['active_count']} path={summary['path']}"
        )
        return 0
    if args.command == "list":
        entries = ranked_user_conclusions(limit=args.limit)
        if args.json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        else:
            print(render_entries(entries))
        return 0
    if args.command == "add":
        entry = add_manual_conclusion(
            conclusion=args.conclusion,
            category=args.category,
            confidence=args.confidence,
            scope=args.scope,
            evidence_path=args.evidence_path,
        )
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
