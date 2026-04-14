from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import CODEX, STATE_DIR, ensure_state_dir
from procedure_candidates import refresh_procedure_candidates
from retrospect_common import write_text_if_changed
from theory_loop import INDEX_PATH as THEORY_LOOP_INDEX_PATH


CURATION_QUEUE_PATH = STATE_DIR / "curation-queue.jsonl"
CURATION_DIGEST_PATH = CODEX / "generated" / "curation-digest.md"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def load_theory_entries() -> list[dict[str, Any]]:
    if not THEORY_LOOP_INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(THEORY_LOOP_INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    normalized["id"] = str(normalized.get("id") or "").strip()
    normalized["kind"] = str(normalized.get("kind") or "curation-candidate").strip()
    normalized["title"] = str(normalized.get("title") or "").strip()
    normalized["summary"] = str(normalized.get("summary") or "").strip()
    normalized["status"] = str(normalized.get("status") or "staged").strip()
    normalized["source"] = str(normalized.get("source") or "manual").strip()
    normalized["scope"] = str(normalized.get("scope") or "project").strip()
    normalized["project_root"] = str(normalized.get("project_root") or "").strip()
    normalized["note_path"] = str(normalized.get("note_path") or "").strip()
    normalized["created_at"] = str(normalized.get("created_at") or now_utc_iso()).strip()
    normalized["updated_at"] = str(normalized.get("updated_at") or normalized["created_at"]).strip()
    normalized["evidence_paths"] = [
        str(path).strip() for path in normalized.get("evidence_paths", []) if str(path).strip()
    ]
    normalized["metadata"] = dict(normalized.get("metadata") or {})
    return normalized


def is_inferred_theory_loop_entry(entry: dict[str, Any]) -> bool:
    return (
        str(entry.get("source") or "").strip() == "theory-loop"
        or str(entry.get("kind") or "").strip() == "validated-theory-loop"
    )


def staged_theory_entries() -> list[dict[str, Any]]:
    staged: list[dict[str, Any]] = []
    for entry in load_theory_entries():
        if not entry.get("validated"):
            continue
        note_path = str(entry.get("note_path") or "").strip()
        if not note_path:
            continue
        checked_at = str(entry.get("checked_at") or entry.get("created_at") or now_utc_iso())
        staged.append(
            normalize_entry(
                {
                    "id": f"theory-loop:{entry.get('id') or Path(note_path).stem}",
                    "kind": "validated-theory-loop",
                    "title": str(entry.get("task") or Path(note_path).stem),
                    "summary": "Validated theory loop ready for curation review.",
                    "status": "staged",
                    "source": "theory-loop",
                    "scope": "project",
                    "project_root": str(entry.get("project_root") or ""),
                    "note_path": note_path,
                    "created_at": str(entry.get("created_at") or checked_at),
                    "updated_at": checked_at,
                    "evidence_paths": [note_path],
                    "metadata": {
                        "validated": True,
                        "checked_at": checked_at,
                    },
                }
            )
        )
    return staged


def merge_entries(existing: list[dict[str, Any]], inferred: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {}
    for entry in existing:
        normalized = normalize_entry(entry)
        if not normalized.get("id"):
            continue
        if is_inferred_theory_loop_entry(normalized):
            continue
        by_id[normalized["id"]] = normalized
    for inferred_entry in inferred:
        by_id[inferred_entry["id"]] = inferred_entry
    entries = list(by_id.values())
    entries.sort(
        key=lambda entry: (
            str(entry.get("updated_at") or ""),
            str(entry.get("title") or ""),
        ),
        reverse=True,
    )
    return entries


def render_digest(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Curation Digest",
        "",
        f"- Generated: `{now_utc_iso()}`",
        f"- Entries: `{len(entries)}`",
        f"- Queue path: `{CURATION_QUEUE_PATH}`",
        "",
    ]
    if not entries:
        lines.extend(["- none", ""])
        return "\n".join(lines)

    kind_counts: dict[str, int] = {}
    for entry in entries:
        kind = str(entry.get("kind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    lines.append("## Counts")
    lines.append("")
    for kind, count in sorted(kind_counts.items()):
        lines.append(f"- `{kind}`: `{count}`")
    lines.append("")

    lines.append("## Recent Entries")
    lines.append("")
    for entry in entries[:12]:
        lines.append(f"- [{entry['kind']}] {entry['title']}")
        lines.append(f"  - status: `{entry['status']}`")
        lines.append(f"  - project_root: `{entry['project_root'] or '-'}`")
        lines.append(f"  - note_path: `{entry['note_path'] or '-'}`")
        lines.append(f"  - updated_at: `{entry['updated_at']}`")
        lines.append(f"  - summary: {entry['summary']}")
    lines.append("")
    return "\n".join(lines)


def refresh_curation_artifacts() -> dict[str, Any]:
    existing = load_jsonl(CURATION_QUEUE_PATH)
    merged = merge_entries(existing, staged_theory_entries())
    write_jsonl(CURATION_QUEUE_PATH, merged)
    write_text_if_changed(CURATION_DIGEST_PATH, render_digest(merged))
    procedure_summary = refresh_procedure_candidates(merged)
    return {
        "queue_path": str(CURATION_QUEUE_PATH),
        "digest_path": str(CURATION_DIGEST_PATH),
        "count": len(merged),
        "procedure_candidate_count": procedure_summary["count"],
        "procedure_markdown_path": procedure_summary["markdown_path"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the lightweight V2 curation queue.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh", help="Refresh the queue from validated theory loops.")
    list_parser = subparsers.add_parser("list", help="List queued curation entries.")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "refresh":
        summary = refresh_curation_artifacts()
        print(
            "curation queue refreshed: "
            f"entries={summary['count']} "
            f"procedures={summary['procedure_candidate_count']} "
            f"queue={summary['queue_path']}"
        )
        return 0
    if args.command == "list":
        entries = load_jsonl(CURATION_QUEUE_PATH)
        if args.json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        else:
            print(render_digest(entries))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
