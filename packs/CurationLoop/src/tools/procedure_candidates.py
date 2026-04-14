from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recall_common import CODEX
from retrospect_common import write_text_if_changed


GENERATED_DIR = CODEX / "generated"
PROCEDURE_CANDIDATES_MD = GENERATED_DIR / "procedure-candidates.md"
PROCEDURE_CANDIDATES_JSON = GENERATED_DIR / "procedure-candidates.json"


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        match = re.match(r"^#{2,3}\s+(.*)$", stripped)
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
        if not bullet or bullet.startswith("[ ]"):
            continue
        bullets.append(bullet)
    return bullets


def candidate_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    note_path_text = str(entry.get("note_path") or "").strip()
    if not note_path_text:
        return None
    note_path = Path(note_path_text)
    if not note_path.exists():
        return None

    text = note_path.read_text(encoding="utf-8")
    sections = parse_sections(text)
    verification = extract_bullets(sections.get("Verification", []))
    probes = extract_bullets(sections.get("Probe Plan", []))
    observations = extract_bullets(sections.get("Observations", []))
    if not verification and not probes:
        return None

    task = str(entry.get("title") or entry.get("task") or note_path.stem).strip()
    checked_at = str(entry.get("updated_at") or entry.get("checked_at") or entry.get("created_at") or "").strip()
    project_root = str(entry.get("project_root") or "").strip()

    return {
        "id": f"procedure:{entry.get('id', note_path.stem)}",
        "title": task,
        "project_root": project_root,
        "note_path": str(note_path),
        "checked_at": checked_at,
        "verification": verification[:4],
        "probes": probes[:4],
        "observations": observations[:3],
        "summary": verification[0] if verification else probes[0],
    }


def render_markdown(candidates: list[dict[str, Any]]) -> str:
    lines = [
        "# Procedure Candidates",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Candidates: `{len(candidates)}`",
        "",
    ]
    if not candidates:
        lines.extend(["- none", ""])
        return "\n".join(lines)

    for candidate in candidates:
        lines.append(f"## {candidate['title']}")
        lines.append("")
        lines.append(f"- Project root: `{candidate['project_root'] or '-'}`")
        lines.append(f"- Note path: `{candidate['note_path']}`")
        lines.append(f"- Checked at: `{candidate['checked_at'] or '-'}`")
        lines.append(f"- Summary: {candidate['summary']}")
        lines.append("")
        if candidate["verification"]:
            lines.append("### Verification")
            lines.append("")
            for item in candidate["verification"]:
                lines.append(f"- {item}")
            lines.append("")
        if candidate["probes"]:
            lines.append("### Probe Signals")
            lines.append("")
            for item in candidate["probes"]:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines)


def refresh_procedure_candidates(entries: list[dict[str, Any]]) -> dict[str, Any]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [candidate for candidate in (candidate_from_entry(entry) for entry in entries) if candidate]
    candidates.sort(
        key=lambda item: (str(item.get("checked_at") or ""), str(item.get("title") or "")),
        reverse=True,
    )
    write_text_if_changed(PROCEDURE_CANDIDATES_JSON, json.dumps(candidates, ensure_ascii=False, indent=2) + "\n")
    write_text_if_changed(PROCEDURE_CANDIDATES_MD, render_markdown(candidates))
    return {
        "json_path": str(PROCEDURE_CANDIDATES_JSON),
        "markdown_path": str(PROCEDURE_CANDIDATES_MD),
        "count": len(candidates),
    }
