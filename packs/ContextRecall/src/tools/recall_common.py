from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from retrospect_common import (
    CODEX,
    HOME,
    MEMORIES,
    SESSIONS,
    build_session_file_map,
    classify_session,
    extract_paths_from_messages,
    group_messages_by_session,
    is_generated_memory_path,
    load_history,
    load_thread_names,
    normalize_space,
    parse_frontmatter,
    parse_iso_to_epoch_ms,
    session_date_label,
    session_ref_label,
    shorten,
    theme_related_skills,
    unique_preserve_order,
)


STATE_DIR = CODEX / "state"
RECALL_DB = STATE_DIR / "recall-index.sqlite3"
RECALL_MANIFEST = STATE_DIR / "recall-manifest.json"
SKILL_ROOTS = (
    CODEX / "skills",
    HOME / ".agents" / "skills",
)
DEFAULT_PROJECT_DOCS = (
    "AGENTS.md",
    "README.md",
    "PLAN.md",
    "PRD.md",
    "TODO.md",
)


@dataclass(frozen=True)
class RecallRecord:
    record_id: str
    source: str
    kind: str
    title: str
    summary: str
    search_text: str
    path: str
    created_ts: int
    updated_ts: int
    canonical: int
    metadata: dict[str, Any]

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.record_id,
            self.source,
            self.kind,
            self.title,
            self.summary,
            self.search_text,
            self.path,
            self.created_ts,
            self.updated_ts,
            self.canonical,
            json.dumps(self.metadata, ensure_ascii=False, sort_keys=True),
        )


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def connect_db() -> sqlite3.Connection:
    ensure_state_dir()
    conn = sqlite3.connect(RECALL_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            search_text TEXT NOT NULL,
            path TEXT NOT NULL,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL,
            canonical INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind);
        CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
        CREATE INDEX IF NOT EXISTS idx_documents_updated_ts ON documents(updated_ts DESC);
        """
    )


def replace_records(conn: sqlite3.Connection, records: Iterable[RecallRecord]) -> int:
    payload = [record.as_row() for record in records]
    with conn:
        conn.execute("DELETE FROM documents")
        conn.executemany(
            """
            INSERT INTO documents (
                id,
                source,
                kind,
                title,
                summary,
                search_text,
                path,
                created_ts,
                updated_ts,
                canonical,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    return len(payload)


def record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"])
    return {
        "id": row["id"],
        "source": row["source"],
        "kind": row["kind"],
        "title": row["title"],
        "summary": row["summary"],
        "search_text": row["search_text"],
        "path": row["path"],
        "created_ts": row["created_ts"],
        "updated_ts": row["updated_ts"],
        "canonical": bool(row["canonical"]),
        "metadata": metadata,
    }


def load_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            id,
            source,
            kind,
            title,
            summary,
            search_text,
            path,
            created_ts,
            updated_ts,
            canonical,
            metadata_json
        FROM documents
        ORDER BY updated_ts DESC, title ASC
        """
    ).fetchall()
    return [record_from_row(row) for row in rows]


def write_manifest(payload: dict[str, Any]) -> None:
    ensure_state_dir()
    RECALL_MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest() -> dict[str, Any]:
    if not RECALL_MANIFEST.exists():
        return {}
    return json.loads(RECALL_MANIFEST.read_text(encoding="utf-8"))


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch_to_ms(value: int | float | str | None) -> int:
    if value is None:
        return 0
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    if numeric <= 0:
        return 0
    if numeric < 1_000_000_000_000:
        return numeric * 1000
    return numeric


def markdown_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def markdown_summary(body: str, fallback: str = "") -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        return shorten(stripped, limit=220)
    return shorten(fallback, limit=220)


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return unique_preserve_order(values)
    text = str(value).strip()
    if not text or text.lower() == "none":
        return []
    parts = [part.strip() for part in re.split(r"[,\n]", text) if part.strip()]
    return unique_preserve_order(parts)


def clamp_search_text(text: str, limit: int = 16000) -> str:
    clean = normalize_space(text)
    if len(clean) <= limit:
        return clean
    return clean[:limit]


def session_file_metadata(session_path: Path) -> dict[str, str]:
    session_id = ""
    cwd = ""
    started_at = ""
    try:
        with session_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if payload.get("type") != "session_meta":
                    continue
                meta = payload.get("payload", {})
                session_id = str(meta.get("id") or "").strip()
                cwd = str(meta.get("cwd") or "").strip()
                started_at = str(meta.get("timestamp") or "").strip()
                break
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        "session_id": session_id,
        "cwd": cwd,
        "started_at": started_at,
    }


def path_project_hints(path_texts: Iterable[str], cwd: str | None = None) -> list[str]:
    hints: list[str] = []
    if cwd:
        hints.append(cwd)
    for path_text in path_texts:
        path = Path(path_text)
        if path.is_file():
            hints.append(str(path.parent))
        else:
            hints.append(str(path))
    return unique_preserve_order([hint for hint in hints if hint and hint.startswith(str(HOME))])


def build_session_records() -> list[RecallRecord]:
    messages = load_history()
    grouped = group_messages_by_session(messages)
    thread_names = load_thread_names()
    session_files = build_session_file_map()
    records: list[RecallRecord] = []

    for session_id, items in grouped.items():
        thread_name = thread_names.get(session_id) or session_ref_label(session_id)
        first_prompt = items[0].text if items else thread_name
        themes = classify_session(items, thread_name)
        related_skills = unique_preserve_order(
            [skill for theme in themes for skill in [theme_related_skills(theme)] if skill and skill != "none"]
        )
        extracted_paths = extract_paths_from_messages(items)
        session_path = session_files.get(session_id)
        session_meta = session_file_metadata(session_path) if session_path and session_path.suffix == ".jsonl" else {}
        cwd = session_meta.get("cwd") or ""
        project_hints = path_project_hints(extracted_paths, cwd=cwd)
        title = thread_name if thread_name != "-" else shorten(first_prompt, limit=72)
        summary = shorten(first_prompt, limit=220)
        date_label = session_date_label(session_path) if session_path else "-"
        combined_text = "\n\n".join(item.text for item in items)
        search_text = clamp_search_text(
            "\n".join(
                [
                    title,
                    summary,
                    " ".join(themes),
                    " ".join(related_skills),
                    " ".join(project_hints),
                    combined_text,
                ]
            )
        )
        metadata = {
            "session_id": session_id,
            "session_ref": session_ref_label(session_id),
            "thread_name": thread_name,
            "date_label": date_label,
            "message_count": len(items),
            "themes": themes,
            "projects": project_hints,
            "paths": unique_preserve_order(
                [str(session_path.resolve())] if session_path and session_path.exists() else []
            )
            + extracted_paths,
            "related_skills": related_skills,
            "cwd": cwd,
            "source_type": items[0].source if items else "unknown",
        }
        records.append(
            RecallRecord(
                record_id=f"session:{session_id}",
                source="session",
                kind="conversation",
                title=title,
                summary=summary,
                search_text=search_text,
                path=str(session_path.resolve()) if session_path and session_path.exists() else "",
                created_ts=epoch_to_ms(items[0].ts if items else 0),
                updated_ts=epoch_to_ms(items[-1].ts if items else 0),
                canonical=0,
                metadata=metadata,
            )
        )

    return records


def build_memory_records() -> list[RecallRecord]:
    records: list[RecallRecord] = []
    for path in sorted(MEMORIES.rglob("*.md")):
        if is_generated_memory_path(path):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = parse_frontmatter(raw)
        if not metadata:
            continue
        title = markdown_title(body, fallback=path.stem.replace("-", " "))
        summary = markdown_summary(body, fallback=str(metadata.get("topic") or path.stem))
        topic = str(metadata.get("topic") or "").strip()
        related_skills = string_list(metadata.get("related_skills"))
        status = str(metadata.get("status") or "").strip()
        source_scope = str(metadata.get("source_scope") or "").strip()
        search_text = clamp_search_text(
            "\n".join(
                [
                    title,
                    summary,
                    topic,
                    source_scope,
                    " ".join(related_skills),
                    body,
                ]
            )
        )
        record_metadata = {
            "topic": topic,
            "status": status,
            "artifact_type": str(metadata.get("artifact_type") or "").strip(),
            "source_scope": source_scope,
            "related_skills": related_skills,
            "projects": [],
            "paths": [str(path.resolve())],
        }
        records.append(
            RecallRecord(
                record_id=f"memory:{path.relative_to(MEMORIES)}",
                source="memory",
                kind="memory",
                title=title,
                summary=summary,
                search_text=search_text,
                path=str(path.resolve()),
                created_ts=0,
                updated_ts=int(path.stat().st_mtime * 1000),
                canonical=1 if status == "canonical" else 0,
                metadata=record_metadata,
            )
        )
    return records


def skill_root_label(skill_path: Path) -> str:
    skill_path_str = str(skill_path)
    if skill_path_str.startswith(str(CODEX / "skills" / ".system")):
        return "system"
    if skill_path_str.startswith(str(CODEX / "skills")):
        return "codex"
    return "agent"


def build_skill_records() -> list[RecallRecord]:
    records: list[RecallRecord] = []
    for root in SKILL_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("SKILL.md")):
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            metadata, body = parse_frontmatter(raw)
            title = str(metadata.get("name") or path.parent.name).strip() or path.parent.name
            summary = str(metadata.get("description") or "").strip() or markdown_summary(body, fallback=title)
            status = str(metadata.get("status") or "").strip()
            domain = str(metadata.get("domain") or "").strip()
            search_text = clamp_search_text(
                "\n".join(
                    [
                        title,
                        summary,
                        domain,
                        body,
                    ]
                )
            )
            root_label = skill_root_label(path)
            record_metadata = {
                "skill_name": title,
                "skill_root": root_label,
                "status": status,
                "domain": domain,
                "projects": [],
                "paths": [str(path.resolve())],
            }
            records.append(
                RecallRecord(
                    record_id=f"skill:{path.parent.name}:{root_label}",
                    source="skill",
                    kind="skill",
                    title=title,
                    summary=summary,
                    search_text=search_text,
                    path=str(path.resolve()),
                    created_ts=0,
                    updated_ts=int(path.stat().st_mtime * 1000),
                    canonical=1 if (status == "canonical" or root_label in {"codex", "system"}) else 0,
                    metadata=record_metadata,
                )
            )
    return records


def rebuild_recall_index() -> dict[str, Any]:
    session_records = build_session_records()
    memory_records = build_memory_records()
    skill_records = build_skill_records()
    all_records = [*session_records, *memory_records, *skill_records]

    conn = connect_db()
    init_db(conn)
    total = replace_records(conn, all_records)
    conn.close()

    summary = {
        "version": 1,
        "synced_at": now_utc_iso(),
        "db_path": str(RECALL_DB),
        "counts": {
            "session": len(session_records),
            "memory": len(memory_records),
            "skill": len(skill_records),
            "total": total,
        },
    }
    write_manifest(summary)
    return summary


def query_tokens(text: str) -> list[str]:
    normalized = normalize_space(text).lower()
    if not normalized:
        return []
    ascii_tokens = re.findall(r"[a-z0-9_./:-]+", normalized)
    ascii_tokens = [token for token in ascii_tokens if len(token) > 1]
    if ascii_tokens:
        return unique_preserve_order([normalized, *ascii_tokens])
    return [normalized]


def score_record(record: dict[str, Any], query: str = "", project: str | None = None) -> float:
    title = record["title"].lower()
    summary = record["summary"].lower()
    search_text = record["search_text"].lower()
    metadata = record["metadata"]
    score = 0.0

    for index, token in enumerate(query_tokens(query)):
        weight = 1.0 if index == 0 else 0.6
        if token and token in title:
            score += 40 * weight
        if token and token in summary:
            score += 22 * weight
        if token and token in search_text:
            score += 10 * weight

    if record["canonical"]:
        score += 8
    if record["kind"] == "memory" and record["canonical"]:
        score += 12
    if record["kind"] == "skill":
        score += 4

    if project:
        project_text = str(Path(project).resolve())
        paths = [str(path) for path in metadata.get("paths", [])]
        projects = [str(item) for item in metadata.get("projects", [])]
        if any(path.startswith(project_text) for path in paths):
            score += 35
        if any(candidate.startswith(project_text) or project_text.startswith(candidate) for candidate in projects):
            score += 25

    updated_ts = int(record.get("updated_ts") or 0)
    if updated_ts:
        age_days = max(0.0, (datetime.now(timezone.utc).timestamp() * 1000 - updated_ts) / 86_400_000)
        score += max(0.0, 8.0 - min(age_days / 7.0, 8.0))

    return round(score, 2)


def rank_records(
    records: Iterable[dict[str, Any]],
    *,
    query: str = "",
    project: str | None = None,
    kinds: set[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for record in records:
        if kinds and record["kind"] not in kinds:
            continue
        score = score_record(record, query=query, project=project)
        if query and score <= 0:
            continue
        if not query and not project and score <= 0:
            continue
        ranked.append({**record, "score": score})
    ranked.sort(key=lambda item: (item["score"], item["updated_ts"], item["canonical"], item["title"]), reverse=True)
    return ranked[:limit]


def discover_project_docs(project: str | None, limit: int = 8) -> list[str]:
    if not project:
        return []
    root = Path(project).expanduser()
    if not root.exists():
        return []
    candidates: list[Path] = []
    for name in DEFAULT_PROJECT_DOCS:
        candidate = root / name
        if candidate.exists():
            candidates.append(candidate)
    docs_dir = root / "docs"
    if docs_dir.exists():
        candidates.extend(sorted(docs_dir.rglob("*.md"))[: max(0, limit - len(candidates))])
    seen: set[str] = set()
    docs: list[str] = []
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        docs.append(resolved)
        if len(docs) >= limit:
            break
    return docs


def default_project_for_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.exists():
        return None
    if path == HOME:
        return None
    return str(path.resolve())
