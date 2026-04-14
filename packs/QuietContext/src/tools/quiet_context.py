from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from hot_context import HOT_CONTEXT_MANIFEST_PATH, refresh_hot_context
from recall_common import CODEX, load_manifest
from platform_build_context import FOCUS_BRIEFS_DIR, FOCUS_MANIFESTS_DIR, write_context_artifacts
from retrospect_common import (
    THEME_PLAYBOOKS,
    build_session_file_map,
    classify_session,
    group_messages_by_session,
    load_history,
    load_thread_names,
    session_date_label,
    session_ref_label,
    shorten,
    theme_slug,
)

try:
    from clamp_document_intake import INTAKE_SUMMARY_PATH
except ImportError:
    INTAKE_SUMMARY_PATH = CODEX / "generated" / "document-intake-summary.json"


GENERATED_DIR = CODEX / "generated"
DAILY_BRIEF_PATH = GENERATED_DIR / "daily-brief.md"
FOCUS_INDEX_PATH = GENERATED_DIR / "focus-briefs.md"
INSTALLED_PACKS_PATH = CODEX / "state" / "installed-packs.json"
CLAMP_ACTION_SUMMARY_PATH = GENERATED_DIR / "clamp-action-summary.json"
CLAMP_ACTION_QUEUE_PATH = CODEX / "memories" / "clamp-action-queue.md"
CURATION_QUEUE_PATH = CODEX / "state" / "curation-queue.jsonl"
PROCEDURE_CANDIDATES_JSON_PATH = GENERATED_DIR / "procedure-candidates.json"


def _load_installed_packs() -> list[dict]:
    if not INSTALLED_PACKS_PATH.exists():
        return []
    return json.loads(INSTALLED_PACKS_PATH.read_text(encoding="utf-8"))


def _load_clamp_action_summary() -> dict:
    if not CLAMP_ACTION_SUMMARY_PATH.exists():
        return {}
    try:
        payload = json.loads(CLAMP_ACTION_SUMMARY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_document_intake_summary() -> dict:
    if not INTAKE_SUMMARY_PATH.exists():
        return {}
    try:
        payload = json.loads(INTAKE_SUMMARY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_hot_context_summary() -> dict:
    if not HOT_CONTEXT_MANIFEST_PATH.exists():
        return {}
    try:
        payload = json.loads(HOT_CONTEXT_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_array(path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _load_jsonl_entries(path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
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


def _recent_sessions(days: int = 3, limit: int = 8) -> tuple[list[dict], list[str]]:
    messages = load_history()
    grouped = group_messages_by_session(messages)
    thread_names = load_thread_names()
    session_files = build_session_file_map()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    sessions: list[dict] = []
    theme_counter: Counter[str] = Counter()

    for session_id, items in grouped.items():
        updated_ts = int(items[-1].ts) * 1000 if int(items[-1].ts) < 1_000_000_000_000 else int(items[-1].ts)
        if updated_ts < cutoff_ms:
            continue
        thread_name = thread_names.get(session_id, "-")
        if thread_name == "-":
            thread_name = shorten(items[0].text, limit=32)
        themes = classify_session(items, thread_name)
        theme_counter.update(themes)
        sessions.append(
            {
                "session_id": session_id,
                "session_ref": session_ref_label(session_id),
                "thread_name": thread_name,
                "summary": shorten(items[0].text, limit=120),
                "updated_ts": updated_ts,
                "date_label": session_date_label(session_files.get(session_id)),
                "themes": themes,
            }
        )

    sessions.sort(key=lambda item: (item["updated_ts"], item["thread_name"]), reverse=True)
    return sessions[:limit], [theme for theme, _ in theme_counter.most_common(5)]


def _focus_themes(top_themes: list[str], limit: int = 4) -> list[str]:
    themes = [theme for theme in top_themes if theme != "General / Follow-Up"]
    return themes[:limit]


def build_focus_briefs(top_themes: list[str]) -> list[dict]:
    FOCUS_BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    FOCUS_MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    active_slugs: set[str] = set()
    entries: list[dict] = []

    for theme in _focus_themes(top_themes):
        slug = theme_slug(theme)
        active_slugs.add(slug)
        brief_path = FOCUS_BRIEFS_DIR / f"{slug}.md"
        manifest_path = FOCUS_MANIFESTS_DIR / f"{slug}.json"
        payload = write_context_artifacts(
            query=theme,
            limit=10,
            brief_path=brief_path,
            manifest_path=manifest_path,
        )
        top_memory = payload["preload"]["top_memories"][0]["title"] if payload["preload"]["top_memories"] else "-"
        top_skill = payload["preload"]["top_skills"][0]["title"] if payload["preload"]["top_skills"] else "-"
        entries.append(
            {
                "theme": theme,
                "slug": slug,
                "brief_path": str(brief_path),
                "manifest_path": str(manifest_path),
                "top_memory": top_memory,
                "top_skill": top_skill,
            }
        )

    for directory in (FOCUS_BRIEFS_DIR, FOCUS_MANIFESTS_DIR):
        for path in directory.glob("*"):
            if path.is_dir():
                continue
            if path.stem not in active_slugs:
                path.unlink(missing_ok=True)

    return entries


def render_focus_index(entries: list[dict]) -> str:
    lines = [
        "# Focus Briefs",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        "",
    ]
    if not entries:
        lines.extend(["- none", ""])
        return "\n".join(lines)
    for entry in entries:
        lines.append(f"- `{entry['theme']}`")
        lines.append(f"  - brief: `{entry['brief_path']}`")
        lines.append(f"  - manifest: `{entry['manifest_path']}`")
        lines.append(f"  - top_memory: `{entry['top_memory']}`")
        lines.append(f"  - top_skill: `{entry['top_skill']}`")
    lines.append("")
    return "\n".join(lines)


def build_daily_brief(*, focus_entries: list[dict], hot_context_summary: dict | None = None) -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    sessions, top_themes = _recent_sessions()
    recall_manifest = load_manifest()
    installed_packs = _load_installed_packs()
    clamp_summary = _load_clamp_action_summary()
    document_intake_summary = _load_document_intake_summary()
    hot_context_summary = hot_context_summary or _load_hot_context_summary()
    curation_entries = _load_jsonl_entries(CURATION_QUEUE_PATH)
    procedure_candidates = _load_json_array(PROCEDURE_CANDIDATES_JSON_PATH)

    lines = [
        "# Daily Brief",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
    ]
    synced_at = recall_manifest.get("synced_at")
    if synced_at:
        lines.append(f"- Recall Index Freshness: `{synced_at}`")
    counts = recall_manifest.get("counts", {})
    if counts:
        lines.append(
            f"- Recall Index Counts: sessions={counts.get('session', 0)}, memories={counts.get('memory', 0)}, skills={counts.get('skill', 0)}"
        )
    if installed_packs:
        latest_packs = ", ".join(
            f"{item.get('id')}@{item.get('version')}" for item in installed_packs[-4:]
        )
        lines.append(f"- Installed Packs: `{latest_packs}`")
    lines.append("")

    clamp_status = str(clamp_summary.get("status") or "").strip()
    required_count = int(clamp_summary.get("required_count") or 0)
    suggested_count = int(clamp_summary.get("suggested_count") or 0)
    promotion_count = int(clamp_summary.get("promotion_candidate_count") or 0)
    retirement_count = int(clamp_summary.get("retirement_hint_count") or 0)
    queue_path = str(clamp_summary.get("queue_path") or CLAMP_ACTION_QUEUE_PATH)

    if clamp_status == "required":
        lines.extend(
            [
                "## CLAMP Action Required",
                "",
                "- User action required. Do not leave these items silent.",
                f"- Queue: `{queue_path}`",
                f"- Required count: `{required_count}`",
                f"- Suggested follow-up: promotions=`{promotion_count}`, retirement=`{retirement_count}`",
                "",
            ]
        )
        for item in clamp_summary.get("top_required", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('kind', '-')}` `{item.get('name', '-')}`: {item.get('summary', '-')}; action: {item.get('suggested_action', '-')}."
            )
        lines.append("")
    elif clamp_status == "suggested":
        lines.extend(
            [
                "## CLAMP Suggested Work",
                "",
                "- No blocking repair is open, but CLAMP has reusable follow-up work queued.",
                f"- Queue: `{queue_path}`",
                f"- Promotion candidates: `{promotion_count}`",
                f"- Retirement hints: `{retirement_count}`",
                "",
            ]
        )
        for item in clamp_summary.get("top_suggested", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('kind', '-')}` `{item.get('name', '-')}`: {item.get('summary', '-')}"
            )
        lines.append("")
    elif clamp_summary:
        lines.extend(
            [
                "## CLAMP Status",
                "",
                "- No open required CLAMP actions.",
                f"- Queue: `{queue_path}`",
                f"- Suggested items: `{suggested_count}`",
                "",
            ]
        )

    intake_counts = document_intake_summary.get("counts", {}) if document_intake_summary else {}
    intake_failed = int(intake_counts.get("failed", 0) or 0)
    intake_low_text = int(intake_counts.get("low_text", 0) or 0)
    if document_intake_summary and (intake_failed or intake_low_text):
        lines.extend(
            [
                "## CLAMP Document Intake",
                "",
                f"- Summary: `{INTAKE_SUMMARY_PATH}`",
                f"- Issues: failed=`{intake_failed}`, low_text=`{intake_low_text}`",
                "",
            ]
        )
        for item in document_intake_summary.get("issues", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('source_rel_path', '-')}` `{item.get('extraction_status', '-')}`: "
                + ", ".join(item.get("errors", [])[:2] or ["review needed"])
            )
        lines.append("")

    if hot_context_summary or curation_entries or procedure_candidates:
        lines.extend(["## Memory Runtime", ""])
        hot_generated_at = str(hot_context_summary.get("generated_at") or "-")
        system_summary = hot_context_summary.get("system", {}) if hot_context_summary else {}
        user_summary = hot_context_summary.get("user", {}) if hot_context_summary else {}
        project_summary = hot_context_summary.get("project_context", {}) if hot_context_summary else {}
        lines.append(f"- Hot context manifest: `{HOT_CONTEXT_MANIFEST_PATH}`")
        lines.append(f"- Hot context freshness: `{hot_generated_at}`")
        lines.append(
            f"- Hot context counts: system=`{system_summary.get('item_count', 0)}`, user=`{user_summary.get('item_count', 0)}`"
        )
        if project_summary:
            lines.append(f"- Last projected project: `{project_summary.get('project', '-')}`")
        lines.append(f"- Curation queue: `{CURATION_QUEUE_PATH}` entries=`{len(curation_entries)}`")
        lines.append(
            f"- Procedure candidates: `{PROCEDURE_CANDIDATES_JSON_PATH}` candidates=`{len(procedure_candidates)}`"
        )
        lines.append("")

    lines.extend(["## Active Themes", ""])
    if not top_themes:
        lines.extend(["- none", ""])
    else:
        for theme in top_themes:
            pointer = THEME_PLAYBOOKS.get(theme)
            if pointer:
                lines.append(f"- `{theme}` -> `{pointer}`")
            else:
                lines.append(f"- `{theme}`")
        lines.append("")

    lines.extend(["## Recent Sessions", ""])
    if not sessions:
        lines.extend(["- none", ""])
    else:
        for session in sessions:
            theme_text = ", ".join(session["themes"][:3]) or "General / Follow-Up"
            lines.append(
                f"- `{session['date_label']}` `{session['session_ref']}` `{session['thread_name']}`: {session['summary']} (themes={theme_text})"
            )
        lines.append("")

    lines.extend(["## Focus Briefs", ""])
    if not focus_entries:
        lines.extend(["- none", ""])
    else:
        for entry in focus_entries:
            lines.append(
                f"- `{entry['theme']}` -> `{entry['brief_path']}` (top_memory=`{entry['top_memory']}`, top_skill=`{entry['top_skill']}`)"
            )
        lines.append("")

    lines.extend(["## Quiet Use", ""])
    lines.extend(
        [
            "- For broad or ambiguous work, consult this brief before reconstructing history manually.",
            "- For a concrete topic or repo, prefer an existing focus brief first, then refresh `task-brief.md` only if the current work falls outside the active themes.",
            "- Treat canonical memory or playbook pointers above as the first files to open, not as optional reading.",
            "",
        ]
    )

    return "\n".join(lines)


def refresh_quiet_context() -> dict:
    _, top_themes = _recent_sessions()
    focus_entries = build_focus_briefs(top_themes)
    hot_context_summary = refresh_hot_context()
    content = build_daily_brief(focus_entries=focus_entries, hot_context_summary=hot_context_summary)
    DAILY_BRIEF_PATH.write_text(content, encoding="utf-8")
    FOCUS_INDEX_PATH.write_text(render_focus_index(focus_entries), encoding="utf-8")
    curation_entries = _load_jsonl_entries(CURATION_QUEUE_PATH)
    procedure_candidates = _load_json_array(PROCEDURE_CANDIDATES_JSON_PATH)
    return {
        "daily_brief": str(DAILY_BRIEF_PATH),
        "focus_index": str(FOCUS_INDEX_PATH),
        "focus_count": len(focus_entries),
        "hot_context": str(HOT_CONTEXT_MANIFEST_PATH),
        "hot_context_generated_at": hot_context_summary.get("generated_at"),
        "curation_count": len(curation_entries),
        "procedure_candidate_count": len(procedure_candidates),
    }


def main() -> int:
    summary = refresh_quiet_context()
    print(
        "quiet context refreshed: "
        f"focus_briefs={summary['focus_count']} "
        f"curation_entries={summary['curation_count']} "
        f"procedures={summary['procedure_candidate_count']} "
        f"daily_brief={summary['daily_brief']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
