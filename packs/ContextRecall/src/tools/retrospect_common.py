from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable
import unicodedata

HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser().resolve()
MEMORIES = CODEX / "memories"
SESSIONS = CODEX / "sessions"
HISTORY = CODEX / "history.jsonl"
SESSION_INDEX = CODEX / "session_index.jsonl"
AI_WORKSPACE = Path(os.environ.get("CLAMP_AI_WORKSPACE", str(HOME / "ai_workspace"))).expanduser().resolve()
GEMINI_BRIDGE = Path(
    os.environ.get("CLAMP_GEMINI_BRIDGE", str(AI_WORKSPACE / "gemini-history-bridge"))
).expanduser().resolve()
GEMINI_LATEST = GEMINI_BRIDGE / "data" / "latest.json"
GEMINI_CONVERSATIONS = GEMINI_BRIDGE / "data" / "conversations"
CAPTURE_ROOT = Path(os.environ.get("CAP_INBOX_ROOT", str(AI_WORKSPACE / "inbox" / "capture"))).expanduser()
STATE = MEMORIES / ".retrospect-state.json"
INDEX = MEMORIES / "INDEX.md"
INVENTORY_LATEST = MEMORIES / "session-inventory-latest.md"
CANDIDATES = MEMORIES / "candidates.md"
FITNESS_REPORT = MEMORIES / "fitness-report.md"
CLAMP_ACTION_QUEUE = MEMORIES / "clamp-action-queue.md"
REVIEW_TRIGGERS = MEMORIES / "review-triggers.json"
INBOX_DIR = MEMORIES / "inbox"
INBOX_INDEX = INBOX_DIR / "INDEX.md"

AUTO_BEGIN = "<!-- BEGIN AUTO-GENERATED:RETROSPECT -->"
AUTO_END = "<!-- END AUTO-GENERATED:RETROSPECT -->"
GEMINI_SESSION_PREFIX = "gemini:"
CAPTURE_SESSION_PREFIX = "capture:"
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc

HOME_PATTERN = re.escape(str(HOME))
PATH_TOKEN_RE = re.compile(
    rf"(?P<path>`(?:~/[^`\n]+|{HOME_PATTERN}/[^`\n]+)`|~/[^\s\"'`()<>，。；：、]+|{HOME_PATTERN}/[^\s\"'`()<>，。；：、]+)"
)
CAPTURE_ENTRY_RE = re.compile(r"^## (?P<time>\d{2}:\d{2})(?::\d{2})? (?P<kind>[A-Za-z0-9_-]+)\s*$")
CAPTURE_META_RE = re.compile(
    r"^<!--\s*cap\s+id=(?P<id>[^\s>]+)\s+created_at=(?P<created_at>[^\s>]+)\s+kind=(?P<kind>[^\s>]+)(?:\s+semantic=(?P<semantic>[^\s>]+))?\s*-->$"
)

MEMORY_REQUIRED_FIELDS = (
    "artifact_type",
    "status",
    "topic",
    "maintainer",
    "source_scope",
    "related_skills",
    "generated",
)

SKILL_REQUIRED_FIELDS = (
    "name",
    "description",
    "contract_version",
    "status",
    "domain",
)

DEFAULT_REVIEW_TRIGGERS = {
    "version": 1,
    "high_risk_paths": [],
    "high_risk_topics": [],
    "failure_signals": [],
    "reframe_signals": [],
    "escalation_targets": {},
}

TOPIC_PATTERNS = [
    ("Networking / Tailscale", ["tailscale", "ssh", "mosh", "derp", "clash", "mihomo", "tailnet"]),
    ("Wechat / Bot Integration", ["企业微信", "wecom", "wechaty", "weixin", "机器人", "bot"]),
    ("Skills / Codex Tooling", ["skill", "mcp", "agent reach", "playwright", "gws", "officecli", "gemini-cli", "codex"]),
    ("Short Drama / Media Generation", ["短剧", "漫剧", "动画", "storyboard", "episode", "shot", "seedance", "sora", "liblib", "renoise", "comfyui", "视频", "图像", "grok", "viddo"]),
    ("Podcast / Transcript", ["播客", "podcast", "小宇宙", "transcript", "funasr"]),
    ("Presentation / Document", ["ppt", "pptx", "bp", "docx", "xlsx", "pdf", "office"]),
    ("Research / Analysis", ["研究", "论文", "paper", "bci", "分析报告", "趋势", "总结", "汇总分析"]),
    ("Archive / Social Review", ["twitter", "x 推文", "bookmarks", "书签", "youtube", "warren"]),
]

THEME_PLAYBOOKS = {
    "Skills / Codex Tooling": str(CODEX / "skills" / "clamp-core"),
    "Research / Analysis": str(CODEX / "memories" / "INDEX.md"),
}


@dataclass(frozen=True)
class HistoryMessage:
    session_id: str
    ts: int
    text: str
    source: str = "codex"
    cwd: str = ""


@dataclass(frozen=True)
class GeminiConversation:
    session_id: str
    conversation_id: str
    title: str
    category: str
    scraped_at: str
    sidebar_index: int
    archive_file: Path | None
    fingerprint: str
    messages: tuple[HistoryMessage, ...]


@dataclass(frozen=True)
class CaptureEntry:
    session_id: str
    capture_id: str
    kind: str
    semantic: str
    created_at: str
    ts: int
    file_path: Path
    body: str


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if not STATE.exists():
        return {
            "version": 1,
            "last_sync_max_ts": 0,
            "last_sync_ran_at": None,
            "last_distill_max_ts": 0,
            "last_distill_ran_at": None,
            "last_weekly_max_ts": 0,
            "last_weekly_ran_at": None,
            "gemini_conversation_fingerprints": {},
        }
    state = json.loads(STATE.read_text())
    state.setdefault("gemini_conversation_fingerprints", {})
    return state


def save_state(state: dict) -> None:
    write_text_if_changed(STATE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


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


def load_codex_history() -> list[HistoryMessage]:
    messages: list[HistoryMessage] = []
    session_files = build_session_file_map()
    session_cwds = {
        session_id: (session_file_metadata(path).get("cwd") or "")
        for session_id, path in session_files.items()
        if path.suffix == ".jsonl"
    }
    if not HISTORY.exists():
        return messages
    for line in HISTORY.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        session_id = obj["session_id"]
        messages.append(
            HistoryMessage(
                session_id=session_id,
                ts=obj["ts"],
                text=obj["text"],
                cwd=session_cwds.get(session_id, ""),
            )
        )
    return messages


def capture_session_id(capture_id: str) -> str:
    return f"{CAPTURE_SESSION_PREFIX}{capture_id}"


def is_capture_session_id(session_id: str) -> bool:
    return session_id.startswith(CAPTURE_SESSION_PREFIX)


def gemini_session_id(conversation_id: str) -> str:
    return f"{GEMINI_SESSION_PREFIX}{conversation_id}"


def is_gemini_session_id(session_id: str) -> bool:
    return session_id.startswith(GEMINI_SESSION_PREFIX)


def session_ref_label(session_id: str) -> str:
    if is_gemini_session_id(session_id):
        return f"g:{session_id.split(':', 1)[1][:8]}"
    if is_capture_session_id(session_id):
        capture_id = session_id.split(":", 1)[1]
        timed_match = re.match(r"(?P<date>\d{8})T(?P<time>\d{6}).*-(?P<tail>\d+)$", capture_id)
        if timed_match:
            return f"c:{timed_match.group('time')}:{timed_match.group('tail')[-4:]}"
        ordinal_match = re.match(r".*-(?P<tail>\d+)$", capture_id)
        if ordinal_match:
            return f"c:{ordinal_match.group('tail')[-4:]}"
        return f"c:{capture_id[:10]}"
    return session_id[:8]


def gemini_thread_name(title: str, category: str) -> str:
    return f"Gemini | {category} | {title}".strip()


def parse_iso_to_epoch_ms(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def gemini_category_themes(category: str) -> list[str]:
    mapping = {
        "AI Tooling": ["Research / Analysis"],
        "X/Twitter": ["Archive / Social Review"],
        "Creative/Media": ["Short Drama / Media Generation"],
        "Product/Business": ["Research / Analysis"],
        "Philosophy/Science": ["Research / Analysis"],
    }
    return list(mapping.get(category, []))


def normalized_capture_semantic(kind: str, semantic: str | None = None) -> str:
    value = str(semantic or "").strip().lower()
    if value in {"todo", "task", "tasks", "reminder", "reminders"}:
        return "todo"
    if value in {"idea", "ideas", "inspiration", "brainstorm", "note", "notes"}:
        return "idea"
    if value in {"reference", "references", "ref", "resource", "resources", "material", "materials", "quote", "quotes", "snippet", "snippets"}:
        return "reference"
    if value:
        return value
    if kind in {"url", "file", "article", "source", "reference"}:
        return "reference"
    return "idea"


def capture_thread_name(kind: str, body: str, semantic: str | None = None) -> str:
    preview = shorten(body.splitlines()[0] if body.splitlines() else body, limit=72)
    normalized = normalized_capture_semantic(kind, semantic)
    if normalized != "idea" and normalized != kind:
        return f"Capture {normalized}/{kind}: {preview}"
    label = normalized if normalized != "idea" else kind
    return f"Capture {label}: {preview}"


def parse_capture_timestamp(file_date: str, time_text: str, created_at: str, ordinal: int) -> int:
    parsed_created_at = parse_iso_to_epoch_ms(created_at)
    if parsed_created_at:
        return parsed_created_at + ordinal

    full_time = time_text if len(time_text) == 8 else f"{time_text}:00"
    try:
        naive = datetime.fromisoformat(f"{file_date}T{full_time}")
        aware = naive.replace(tzinfo=LOCAL_TZ)
        return int(aware.timestamp() * 1000) + ordinal
    except ValueError:
        return ordinal


@lru_cache(maxsize=1)
def load_capture_entries() -> tuple[CaptureEntry, ...]:
    if not CAPTURE_ROOT.exists():
        return ()

    entries: list[CaptureEntry] = []
    for path in sorted(CAPTURE_ROOT.glob("*.md")):
        lines = path.read_text().splitlines()
        ordinal = 0
        idx = 0
        while idx < len(lines):
            header_match = CAPTURE_ENTRY_RE.match(lines[idx].strip())
            if not header_match:
                idx += 1
                continue

            ordinal += 1
            time_text = header_match.group("time")
            kind = header_match.group("kind")
            next_idx = idx + 1
            body_lines: list[str] = []
            while next_idx < len(lines) and not CAPTURE_ENTRY_RE.match(lines[next_idx].strip()):
                body_lines.append(lines[next_idx])
                next_idx += 1

            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()

            capture_id = f"{path.stem}-{ordinal:04d}"
            created_at = ""
            semantic = normalized_capture_semantic(kind)
            if body_lines:
                meta_match = CAPTURE_META_RE.match(body_lines[0].strip())
                if meta_match:
                    capture_id = meta_match.group("id")
                    created_at = meta_match.group("created_at")
                    kind = meta_match.group("kind") or kind
                    semantic = normalized_capture_semantic(kind, meta_match.group("semantic"))
                    body_lines.pop(0)
                    while body_lines and not body_lines[0].strip():
                        body_lines.pop(0)

            body = "\n".join(body_lines).strip()
            if body:
                entries.append(
                    CaptureEntry(
                        session_id=capture_session_id(capture_id),
                        capture_id=capture_id,
                        kind=kind,
                        semantic=semantic,
                        created_at=created_at,
                        ts=parse_capture_timestamp(path.stem, time_text, created_at, ordinal),
                        file_path=path,
                        body=body,
                    )
                )

            idx = next_idx

    return tuple(entries)


def load_capture_history() -> list[HistoryMessage]:
    return [
        HistoryMessage(
            session_id=entry.session_id,
            ts=entry.ts,
            text=entry.body,
            source="capture",
        )
        for entry in load_capture_entries()
    ]


def load_gemini_conversations() -> list[GeminiConversation]:
    if not GEMINI_LATEST.exists():
        return []

    try:
        payload = json.loads(GEMINI_LATEST.read_text())
    except json.JSONDecodeError:
        return []

    conversations: list[GeminiConversation] = []
    for item in payload.get("conversations", []):
        conversation_id = str(item.get("conversationId") or "").strip()
        if not conversation_id:
            continue
        session_id = gemini_session_id(conversation_id)
        title = str(item.get("title") or conversation_id).strip() or conversation_id
        category = str(item.get("category") or "Other").strip() or "Other"
        scraped_at = str(item.get("scrapedAt") or "").strip()
        sidebar_index = int(item.get("sidebarIndex") or 0)
        archive_path = item.get("files", {}).get("archiveFile")
        archive_file = Path(str(archive_path)).expanduser() if archive_path else None
        base_ts = parse_iso_to_epoch_ms(scraped_at)

        raw_turns = [
            {
                "role": str(turn.get("role") or "").strip(),
                "text": str(turn.get("text") or "").strip(),
            }
            for turn in item.get("turns", [])
            if str(turn.get("text") or "").strip()
        ]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "title": title,
                    "category": category,
                    "turns": raw_turns,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        messages = tuple(
            HistoryMessage(
                session_id=session_id,
                ts=base_ts + idx,
                text=turn["text"],
                source="gemini",
            )
            for idx, turn in enumerate(raw_turns)
        )
        conversations.append(
            GeminiConversation(
                session_id=session_id,
                conversation_id=conversation_id,
                title=title,
                category=category,
                scraped_at=scraped_at,
                sidebar_index=sidebar_index,
                archive_file=archive_file,
                fingerprint=fingerprint,
                messages=messages,
            )
        )

    conversations.sort(
        key=lambda conversation: (
            parse_iso_to_epoch_ms(conversation.scraped_at),
            -conversation.sidebar_index,
            conversation.conversation_id,
        )
    )
    return conversations


def current_gemini_fingerprints() -> dict[str, str]:
    return {conversation.conversation_id: conversation.fingerprint for conversation in load_gemini_conversations()}


def load_gemini_history() -> list[HistoryMessage]:
    messages: list[HistoryMessage] = []
    for conversation in load_gemini_conversations():
        messages.extend(conversation.messages)
    return messages


def load_history() -> list[HistoryMessage]:
    messages = load_codex_history()
    messages.extend(load_capture_history())
    messages.extend(load_gemini_history())
    messages.sort(key=lambda item: (item.ts, item.session_id))
    return messages


def load_thread_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if SESSION_INDEX.exists():
        for line in SESSION_INDEX.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            names[obj["id"]] = obj.get("thread_name") or "-"
    for conversation in load_gemini_conversations():
        names[conversation.session_id] = gemini_thread_name(conversation.title, conversation.category)
    for entry in load_capture_entries():
        names[entry.session_id] = capture_thread_name(entry.kind, entry.body, entry.semantic)
    return names


def build_session_file_map() -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path in SESSIONS.rglob("*.jsonl"):
        try:
            first_line = path.read_text().splitlines()[0]
            payload = json.loads(first_line)
            sid = payload.get("payload", {}).get("id")
        except (IndexError, json.JSONDecodeError, OSError):
            sid = None
        if sid:
            mapping[sid] = path
    for conversation in load_gemini_conversations():
        if conversation.archive_file:
            mapping[conversation.session_id] = conversation.archive_file
    for entry in load_capture_entries():
        mapping[entry.session_id] = entry.file_path
    return mapping


def group_messages_by_session(messages: Iterable[HistoryMessage]) -> dict[str, list[HistoryMessage]]:
    grouped: dict[str, list[HistoryMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.session_id].append(message)
    for items in grouped.values():
        items.sort(key=lambda item: item.ts)
    return dict(grouped)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def shorten(text: str, limit: int = 90) -> str:
    clean = normalize_space(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


@lru_cache(maxsize=512)
def gemini_path_date_label(path_text: str) -> str:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text())
        scraped_at = str(payload.get("scrapedAt") or "").strip()
        if scraped_at:
            date = datetime.fromisoformat(scraped_at.replace("Z", "+00:00")).date().isoformat()
            return f"gemini/{date}"
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    try:
        date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        return f"gemini/{date}"
    except OSError:
        return "gemini/-"


@lru_cache(maxsize=128)
def capture_path_date_label(path_text: str) -> str:
    path = Path(path_text)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
        return f"capture/{path.stem}"
    try:
        date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        return f"capture/{date}"
    except OSError:
        return "capture/-"


def session_date_label(path: Path | None) -> str:
    if path is None:
        return "-"
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    gemini_root = GEMINI_BRIDGE.resolve() if GEMINI_BRIDGE.exists() else GEMINI_BRIDGE
    capture_root = CAPTURE_ROOT.resolve() if CAPTURE_ROOT.exists() else CAPTURE_ROOT
    if str(resolved).startswith(str(gemini_root)) or str(path).startswith(str(GEMINI_BRIDGE)):
        return gemini_path_date_label(str(resolved))
    if str(resolved).startswith(str(capture_root)) or str(path).startswith(str(CAPTURE_ROOT)):
        return capture_path_date_label(str(resolved))
    parts = resolved.parts[-4:-1]
    return "/".join(parts)


def markdown_table_escape(text: str) -> str:
    return normalize_space(text).replace("|", "\\|")


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text

    lines = text.splitlines()
    metadata: dict[str, object] = {}
    end_idx = None
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() == "---":
            end_idx = idx
            break
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        raw_value = value.strip()
        if raw_value.lower() == "true":
            parsed: object = True
        elif raw_value.lower() == "false":
            parsed = False
        elif re.fullmatch(r"-?\d+", raw_value):
            parsed = int(raw_value)
        else:
            parsed = raw_value
        metadata[key] = parsed

    if end_idx is None:
        return {}, text
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    return metadata, body


def load_markdown_frontmatter(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    metadata, _ = parse_frontmatter(path.read_text())
    return metadata


def _format_frontmatter_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_frontmatter(metadata: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {_format_frontmatter_value(value)}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def with_frontmatter(content: str, metadata: dict[str, object]) -> str:
    _, body = parse_frontmatter(content)
    body = body.lstrip("\n")
    return render_frontmatter(metadata) + body


def generated_memory_metadata(
    artifact_type: str,
    topic: str,
    source_scope: str,
    related_skills: str = "none",
) -> dict[str, object]:
    return {
        "artifact_type": artifact_type,
        "status": "generated",
        "topic": topic,
        "maintainer": "codex-retrospect",
        "source_scope": source_scope,
        "related_skills": related_skills,
        "generated": True,
    }


def wrap_generated_markdown(
    content: str,
    *,
    artifact_type: str,
    topic: str,
    source_scope: str,
    related_skills: str = "none",
) -> str:
    metadata = generated_memory_metadata(
        artifact_type=artifact_type,
        topic=topic,
        source_scope=source_scope,
        related_skills=related_skills,
    )
    wrapped = with_frontmatter(content, metadata)
    if not wrapped.endswith("\n"):
        wrapped += "\n"
    return wrapped


def generated_memory_paths() -> set[Path]:
    generated = {
        INVENTORY_LATEST,
        CANDIDATES,
        FITNESS_REPORT,
        CLAMP_ACTION_QUEUE,
        INBOX_INDEX,
    }
    formula_index_dir = MEMORIES / "short-drama-kb" / "formula-index"
    if formula_index_dir.exists():
        for path in formula_index_dir.rglob("*.md"):
            if path.name != "INDEX.md":
                generated.add(path)
    return generated


def is_generated_memory_path(path: Path) -> bool:
    return path in generated_memory_paths() or path.parent == INBOX_DIR


def load_review_triggers() -> dict[str, object]:
    triggers = dict(DEFAULT_REVIEW_TRIGGERS)
    if REVIEW_TRIGGERS.exists():
        loaded = json.loads(REVIEW_TRIGGERS.read_text())
        triggers.update(loaded)
    triggers["high_risk_paths"] = list(triggers.get("high_risk_paths", []))
    triggers["high_risk_topics"] = list(triggers.get("high_risk_topics", []))
    triggers["failure_signals"] = list(triggers.get("failure_signals", []))
    triggers["reframe_signals"] = list(triggers.get("reframe_signals", []))
    triggers["escalation_targets"] = dict(triggers.get("escalation_targets", {}))
    return triggers


def collect_signal_matches(text: str, signals: Iterable[str]) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for signal in signals:
        lowered_signal = signal.lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9 ._-]*", lowered_signal):
            pattern = rf"(?<![a-z0-9]){re.escape(lowered_signal)}(?![a-z0-9])"
            matched = re.search(pattern, lowered) is not None
        else:
            matched = lowered_signal in lowered
        if matched:
            matches.append(signal)
    return matches


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_paths_from_messages(items: list[HistoryMessage]) -> list[str]:
    paths: list[str] = []
    for item in items:
        for match in PATH_TOKEN_RE.finditer(item.text):
            raw = match.group("path").rstrip(".,)")
            paths.append(expand_home(raw))
    return unique_preserve_order(paths)


def high_risk_path_matches(items: list[HistoryMessage], triggers: dict[str, object] | None = None) -> list[str]:
    active_triggers = triggers or load_review_triggers()
    paths = extract_paths_from_messages(items)
    configured = [str(path) for path in active_triggers.get("high_risk_paths", [])]
    matches: list[str] = []
    for candidate in configured:
        if any(path.startswith(candidate) for path in paths):
            matches.append(candidate)
    return matches


def review_trigger_matches(
    items: list[HistoryMessage],
    themes: list[str],
    triggers: dict[str, object] | None = None,
) -> dict[str, list[str]]:
    active_triggers = triggers or load_review_triggers()
    joined = " ".join(item.text for item in items)
    matched_topics = [theme for theme in themes if theme in active_triggers.get("high_risk_topics", [])]
    matched_paths = high_risk_path_matches(items, active_triggers)
    matched_failures = collect_signal_matches(joined, active_triggers.get("failure_signals", []))
    matched_reframes = collect_signal_matches(joined, active_triggers.get("reframe_signals", []))
    return {
        "topics": unique_preserve_order(matched_topics),
        "paths": unique_preserve_order(matched_paths),
        "failure_signals": unique_preserve_order(matched_failures),
        "reframe_signals": unique_preserve_order(matched_reframes),
    }


def failure_signal_count(items: list[HistoryMessage], triggers: dict[str, object] | None = None) -> int:
    active_triggers = triggers or load_review_triggers()
    total = 0
    for item in items:
        total += len(collect_signal_matches(item.text, active_triggers.get("failure_signals", [])))
    return total


def escalation_targets_for_themes(
    themes: list[str],
    triggers: dict[str, object] | None = None,
) -> list[tuple[str, str]]:
    active_triggers = triggers or load_review_triggers()
    mapping = active_triggers.get("escalation_targets", {})
    matches: list[tuple[str, str]] = []
    for theme in themes:
        target = mapping.get(theme)
        if target:
            matches.append((theme, str(target)))
    return matches


def pointer_to_skill_name(pointer: str | None) -> str | None:
    if not pointer:
        return None
    path = Path(pointer)
    parts = path.parts
    if "skills" not in parts:
        return None
    idx = parts.index("skills")
    if idx + 1 >= len(parts):
        return None
    name = parts[idx + 1]
    if name == ".system" and idx + 2 < len(parts):
        return parts[idx + 2]
    return name


def theme_related_skills(theme: str) -> str:
    skill_name = pointer_to_skill_name(THEME_PLAYBOOKS.get(theme))
    return skill_name or "none"


def build_inventory_markdown(messages: list[HistoryMessage]) -> str:
    grouped = group_messages_by_session(messages)
    thread_names = load_thread_names()
    session_files = build_session_file_map()
    rows: list[str] = []
    for session_id in sorted(grouped, key=lambda sid: grouped[sid][0].ts):
        items = grouped[session_id]
        path = session_files.get(session_id)
        date = session_date_label(path)
        thread_name = thread_names.get(session_id, "-")
        first_prompt = shorten(items[0].text)
        source = items[0].source
        rows.append(
            f"| `{date}` | `{source}` | `{session_ref_label(session_id)}` | {markdown_table_escape(thread_name)} | {len(items)} | {markdown_table_escape(first_prompt)} |"
        )

    lines = [
        "# Session Inventory (Latest)",
        "",
        "This file is automatically regenerated from `~/.codex/history.jsonl`, the `~/.codex/sessions/` tree, the capture inbox feed, and the latest Gemini history snapshot when available.",
        "",
        "`session_index.jsonl` is treated as supplemental metadata only.",
        "",
        "| Date | Source | Session ID | Thread | Messages | First Prompt |",
        "| --- | --- | --- | --- | ---: | --- |",
        *rows,
        "",
    ]
    return "\n".join(lines)


def extract_existing_manual_index_paths(index_text: str) -> set[str]:
    paths = set()
    auto_block_pattern = re.compile(rf"{re.escape(AUTO_BEGIN)}.*?{re.escape(AUTO_END)}", re.S)
    manual_text = auto_block_pattern.sub("", index_text)
    for match in PATH_TOKEN_RE.finditer(manual_text):
        token = match.group("path")
        paths.add(expand_home(token))
    return paths


def expand_home(path_text: str) -> str:
    if path_text.startswith("`") and path_text.endswith("`"):
        path_text = path_text[1:-1]
    if path_text.startswith("~/"):
        return str(HOME / path_text[2:])
    return path_text


def should_track_path(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        return False
    if str(resolved).startswith(str(CODEX / "sessions")):
        return False
    if str(resolved).startswith(str(CODEX / "shell_snapshots")):
        return False
    if str(resolved).startswith(str(HOME / "Library")):
        return False
    if str(resolved).startswith(str(HOME / ".playwright-cli")):
        return False
    if str(resolved).startswith(str(HOME / ".claude")):
        return False
    if str(resolved).startswith(str(HOME / ".gemini")):
        return False
    if resolved == HOME or resolved == CODEX:
        return False
    try:
        rel_parts = resolved.relative_to(HOME).parts
    except ValueError:
        return False
    if any(part.startswith(".") for part in rel_parts):
        return False
    if resolved.is_dir():
        return len(rel_parts) <= 2
    if resolved.suffix.lower() not in {".md", ".txt", ".pdf", ".pptx", ".docx", ".xlsx", ".json", ".csv", ".png", ".jpg", ".jpeg"}:
        return False
    return len(rel_parts) == 1


def discover_working_paths(messages: list[HistoryMessage], manual_index_paths: set[str]) -> list[Path]:
    counts: dict[Path, int] = defaultdict(int)
    last_ts: dict[Path, int] = {}
    cwd_paths: set[Path] = set()

    def register_path(path: Path, ts: int, *, from_cwd: bool = False) -> None:
        if not should_track_path(path):
            return
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            return
        if str(resolved) in manual_index_paths:
            return
        counts[resolved] += 3 if from_cwd else 1
        last_ts[resolved] = max(ts, last_ts.get(resolved, 0))
        if from_cwd:
            cwd_paths.add(resolved)

    for message in messages:
        if message.cwd:
            register_path(Path(expand_home(message.cwd)), message.ts, from_cwd=True)
        for match in PATH_TOKEN_RE.finditer(message.text):
            raw = match.group("path").rstrip(".,)")
            register_path(Path(expand_home(raw)), message.ts)

    prioritized_cwds = sorted(
        cwd_paths,
        key=lambda path: (last_ts.get(path, 0), counts.get(path, 0), len(str(path))),
        reverse=True,
    )
    sorted_paths = sorted(
        counts,
        key=lambda path: (counts[path], last_ts[path], len(str(path))),
        reverse=True,
    )

    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in prioritized_cwds + sorted_paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered[:20]


def render_auto_index_block(messages: list[HistoryMessage], manual_index_paths: set[str]) -> str:
    working_paths = discover_working_paths(messages, manual_index_paths)
    lines = [
        AUTO_BEGIN,
        "## Automation",
        "",
        "- `session-inventory-latest.md`",
        "  - Automatically regenerated current inventory for all discovered sessions.",
        "- `candidates.md`",
        "  - Automatically generated candidate insights, pitfalls, and follow-up topics from new session activity.",
        "- `inbox/INDEX.md`",
        "  - Weekly topic inbox index with per-theme review files.",
        "- `fitness-report.md`",
        "  - Contract and pointer health report for memories, skills, and retrospective outputs.",
        "- `clamp-action-queue.md`",
        "  - Automatically generated CLAMP action queue for required source repairs, promotion candidates, and retirement hints.",
        "",
        "## Auto-Tracked Working Paths",
        "",
    ]
    if not working_paths:
        lines.append("- No auto-tracked working paths yet.")
    else:
        for path in working_paths:
            kind = "directory" if path.is_dir() else "file"
            lines.append(f"- `{path}`")
            lines.append(f"  - Auto-tracked local {kind} referenced in session history.")
    lines.append(AUTO_END)
    return "\n".join(lines)


def update_index_auto_block(messages: list[HistoryMessage]) -> str:
    current = INDEX.read_text() if INDEX.exists() else ""
    manual_index_paths = extract_existing_manual_index_paths(current)
    replacement = render_auto_index_block(messages, manual_index_paths)
    pattern = re.compile(rf"{re.escape(AUTO_BEGIN)}.*?{re.escape(AUTO_END)}", re.S)
    if pattern.search(current):
        return pattern.sub(replacement, current)
    if current and not current.endswith("\n"):
        current += "\n"
    return current + "\n" + replacement + "\n"


def classify_session(items: list[HistoryMessage], thread_name: str) -> list[str]:
    text = " ".join([thread_name, *[item.text for item in items]]).lower()
    themes: list[str] = []
    if thread_name.startswith("Gemini | "):
        parts = thread_name.split("|", 2)
        if len(parts) >= 2:
            themes.extend(gemini_category_themes(parts[1].strip()))
    for theme, keywords in TOPIC_PATTERNS:
        if any(keyword.lower() in text for keyword in keywords):
            themes.append(theme)
    themes = unique_preserve_order(themes)
    return themes or ["General / Follow-Up"]


def write_text_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def theme_slug(theme: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", theme).encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return ascii_text or "general-manual-review"


def reframe_signal(items: list[HistoryMessage]) -> bool:
    matches = review_trigger_matches(items, [], load_review_triggers())
    return bool(matches["reframe_signals"])
