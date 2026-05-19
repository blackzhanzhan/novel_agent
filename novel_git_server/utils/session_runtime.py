from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any


ALLOWED_AGENT_KEYS = {"world_agent", "outline_agent", "style_agent", "continuation_agent", "review_agent"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_dev_repo_root(dev_repo_root: str | Path | None = None) -> Path:
    if dev_repo_root:
        return Path(dev_repo_root).resolve()
    return Path(__file__).resolve().parents[2] / "dev_repo"


def delete_book_conversations(dev_repo_root: str | Path | None, book_id: str) -> int:
    removed = 0
    conv_root = resolve_dev_repo_root(dev_repo_root) / "conversations"
    for agent_key in ALLOWED_AGENT_KEYS:
        agent_dir = conv_root / agent_key
        if not agent_dir.is_dir():
            continue
        index_path = agent_dir / f"{book_id}.index.json"
        conversation_ids: set[str] = set()
        if index_path.exists():
            try:
                index_payload = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                index_payload = {}
            if isinstance(index_payload, dict):
                active_id = index_payload.get("active_conversation_id")
                if isinstance(active_id, str) and active_id.strip():
                    conversation_ids.add(active_id.strip())
                for item in index_payload.get("conversations") or []:
                    if not isinstance(item, dict):
                        continue
                    conversation_id = item.get("conversation_id")
                    if isinstance(conversation_id, str) and conversation_id.strip():
                        conversation_ids.add(conversation_id.strip())

        targets = [index_path]
        targets.extend(agent_dir / f"{book_id}__{_safe_file_stem(conversation_id)}.jsonl" for conversation_id in conversation_ids)
        for filepath in dict.fromkeys(targets):
            try:
                os.remove(filepath)
                removed += 1
            except FileNotFoundError:
                pass
    return removed


def route_agent_to_session_agent(agent_key: str) -> str:
    normalized = (agent_key or "").strip()
    mapping = {
        "world_model": "world_agent",
        "outline": "outline_agent",
        "style_guide": "style_agent",
        "continuation": "continuation_agent",
        "continuation_agent": "continuation_agent",
        "review": "review_agent",
        "review_agent": "review_agent",
        "world_agent": "world_agent",
        "outline_agent": "outline_agent",
        "style_agent": "style_agent",
    }
    resolved = mapping.get(normalized, normalized)
    if resolved not in ALLOWED_AGENT_KEYS:
        raise ValueError(f"unsupported_agent_key:{normalized}")
    return resolved


def _safe_file_stem(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "conversation"
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)
    text = text.strip("._-")
    return text or "conversation"


def _agent_dir(dev_repo_root: str | Path | None, agent_key: str) -> Path:
    root = resolve_dev_repo_root(dev_repo_root)
    session_agent = route_agent_to_session_agent(agent_key)
    path = root / "conversations" / session_agent
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(dev_repo_root: str | Path | None, book_id: str, agent_key: str) -> Path:
    return _agent_dir(dev_repo_root, agent_key) / f"{book_id}.index.json"


def _conversation_path(
    dev_repo_root: str | Path | None,
    book_id: str,
    agent_key: str,
    conversation_id: str,
) -> Path:
    safe_id = _safe_file_stem(conversation_id)
    return _agent_dir(dev_repo_root, agent_key) / f"{book_id}__{safe_id}.jsonl"


def load_agent_index(dev_repo_root: str | Path | None, book_id: str, agent_key: str) -> dict[str, Any]:
    index_path = _index_path(dev_repo_root, book_id, agent_key)
    if not index_path.exists():
        return {
            "book_id": book_id,
            "agent_key": route_agent_to_session_agent(agent_key),
            "active_conversation_id": None,
            "conversations": [],
        }
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "book_id": book_id,
        "agent_key": route_agent_to_session_agent(agent_key),
        "active_conversation_id": payload.get("active_conversation_id"),
        "conversations": list(payload.get("conversations") or []),
    }


def save_agent_index(dev_repo_root: str | Path | None, book_id: str, agent_key: str, payload: dict[str, Any]) -> None:
    index_path = _index_path(dev_repo_root, book_id, agent_key)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_conversation_messages(
    dev_repo_root: str | Path | None,
    book_id: str,
    agent_key: str,
    conversation_id: str,
) -> list[dict[str, Any]]:
    path = _conversation_path(dev_repo_root, book_id, agent_key, conversation_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_conversation_records(
    dev_repo_root: str | Path | None,
    book_id: str,
    agent_key: str,
    conversation_id: str,
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return
    path = _conversation_path(dev_repo_root, book_id, agent_key, conversation_id)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_conversation_records(
    dev_repo_root: str | Path | None,
    book_id: str,
    agent_key: str,
    conversation_id: str,
    records: list[dict[str, Any]],
) -> None:
    path = _conversation_path(dev_repo_root, book_id, agent_key, conversation_id)
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(payload, encoding="utf-8")


def _derive_title(existing_messages: list[dict[str, Any]], user_text: str) -> str:
    for item in existing_messages:
        if item.get("role") == "user":
            text = str(item.get("text") or "").strip()
            if text:
                return text[:40]
    return (user_text or "").strip()[:40] or "未命名会话"


def _default_title(active_file: str, title: str | None = None) -> str:
    if isinstance(title, str) and title.strip():
        return title.strip()[:40]
    stem = Path(active_file).name if active_file else "未命名会话"
    return f"{stem} 会话"


def _find_conversation(conversations: list[dict[str, Any]], conversation_id: str) -> tuple[int, dict[str, Any] | None]:
    for idx, item in enumerate(conversations):
        if item.get("conversation_id") == conversation_id:
            return idx, item
    return -1, None


def _normalize_visible_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in conversations if not item.get("archived")]


def _selected_upstream_conversation_id(
    conversations: list[dict[str, Any]],
    conversation_id: str | None,
) -> str | None:
    if not conversation_id:
        return None
    _, item = _find_conversation(conversations, conversation_id)
    if not item:
        return None
    raw_upstream = item.get("upstream_conversation_id")
    return raw_upstream if isinstance(raw_upstream, str) and raw_upstream.strip() else None


def create_conversation(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    active_file: str,
    title: str | None = None,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversation_id = f"conv_{token_hex(8)}"
    now = utc_now()
    meta = {
        "conversation_id": conversation_id,
        "title": _default_title(active_file, title),
        "created_at": now,
        "updated_at": now,
        "last_active_file": active_file,
        "message_count": 0,
        "upstream_conversation_id": None,
        "archived": False,
    }
    conversations = [meta, *index_payload.get("conversations", [])]
    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": conversation_id,
            "conversations": conversations,
        },
    )
    _conversation_path(dev_repo_root, book_id, session_agent, conversation_id).touch(exist_ok=True)
    return get_agent_context(dev_repo_root, book_id=book_id, agent_key=session_agent, conversation_id=conversation_id)


def activate_conversation(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversations = list(index_payload.get("conversations", []))
    _, item = _find_conversation(conversations, conversation_id)
    if item is None or item.get("archived"):
        raise ValueError("conversation_not_found")
    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": conversation_id,
            "conversations": conversations,
        },
    )
    return get_agent_context(dev_repo_root, book_id=book_id, agent_key=session_agent, conversation_id=conversation_id)


def rename_conversation(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str,
    title: str,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversations = list(index_payload.get("conversations", []))
    idx, item = _find_conversation(conversations, conversation_id)
    if item is None:
        raise ValueError("conversation_not_found")
    updated = dict(item)
    updated["title"] = _default_title(updated.get("last_active_file", ""), title)
    updated["updated_at"] = utc_now()
    conversations[idx] = updated
    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": index_payload.get("active_conversation_id"),
            "conversations": conversations,
        },
    )
    return get_agent_context(
        dev_repo_root,
        book_id=book_id,
        agent_key=session_agent,
        conversation_id=index_payload.get("active_conversation_id") or conversation_id,
    )


def archive_conversation(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversations = list(index_payload.get("conversations", []))
    idx, item = _find_conversation(conversations, conversation_id)
    if item is None:
        raise ValueError("conversation_not_found")
    updated = dict(item)
    updated["archived"] = True
    updated["updated_at"] = utc_now()
    conversations[idx] = updated

    next_active = index_payload.get("active_conversation_id")
    if next_active == conversation_id:
        visible = _normalize_visible_conversations(conversations)
        next_active = visible[0]["conversation_id"] if visible else None

    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": next_active,
            "conversations": conversations,
        },
    )
    return get_agent_context(
        dev_repo_root,
        book_id=book_id,
        agent_key=session_agent,
        conversation_id=next_active,
    )


def delete_conversation(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversations = list(index_payload.get("conversations", []))
    idx, item = _find_conversation(conversations, conversation_id)
    if item is None:
        raise ValueError("conversation_not_found")

    del conversations[idx]

    next_active = index_payload.get("active_conversation_id")
    if next_active == conversation_id:
        visible = _normalize_visible_conversations(conversations)
        next_active = visible[0]["conversation_id"] if visible else None

    conversation_path = _conversation_path(dev_repo_root, book_id, session_agent, conversation_id)
    try:
        conversation_path.unlink(missing_ok=True)
    except TypeError:
        if conversation_path.exists():
            conversation_path.unlink()

    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": next_active,
            "conversations": conversations,
        },
    )
    return get_agent_context(
        dev_repo_root,
        book_id=book_id,
        agent_key=session_agent,
        conversation_id=next_active,
    )


def persist_turn(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str,
    upstream_conversation_id: str | None,
    active_file: str,
    user_text: str,
    assistant_text: str,
    status: str = "done",
    rewrite_user_message_id: str | None = None,
) -> None:
    if not conversation_id or not conversation_id.strip():
        return

    session_agent = route_agent_to_session_agent(agent_key)
    existing_messages = read_conversation_messages(dev_repo_root, book_id, session_agent, conversation_id)
    retained_messages = existing_messages
    rewrite_target = rewrite_user_message_id.strip() if isinstance(rewrite_user_message_id, str) and rewrite_user_message_id.strip() else None
    rewrite_applied = False
    if rewrite_target:
        target_index = next(
            (
                idx
                for idx, item in enumerate(existing_messages)
                if item.get("id") == rewrite_target and item.get("role") == "user"
            ),
            -1,
        )
        if target_index >= 0 and not any(item.get("role") == "user" for item in existing_messages[target_index + 1:]):
            retained_messages = existing_messages[:target_index]
            rewrite_applied = True

    title = _derive_title(retained_messages, user_text)
    now = utc_now()

    records = [
        {
            "id": f"user_{datetime.now().timestamp()}",
            "ts": now,
            "role": "user",
            "text": user_text,
            "conversation_id": conversation_id,
            "upstream_conversation_id": upstream_conversation_id,
            "active_file": active_file,
            "status": "done",
        },
        {
            "id": f"assistant_{datetime.now().timestamp()}",
            "ts": now,
            "role": "assistant",
            "text": assistant_text,
            "conversation_id": conversation_id,
            "upstream_conversation_id": upstream_conversation_id,
            "active_file": active_file,
            "status": status,
        },
    ]
    all_messages = retained_messages + records
    if rewrite_applied:
        write_conversation_records(dev_repo_root, book_id, session_agent, conversation_id, all_messages)
    else:
        append_conversation_records(dev_repo_root, book_id, session_agent, conversation_id, records)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    conversations = [item for item in index_payload.get("conversations", []) if item.get("conversation_id") != conversation_id]

    created_at = now
    for item in index_payload.get("conversations", []):
        if item.get("conversation_id") == conversation_id and item.get("created_at"):
            created_at = item["created_at"]
            break

    conversations.insert(
        0,
        {
            "conversation_id": conversation_id,
            "title": title,
            "created_at": created_at,
            "updated_at": now,
            "last_active_file": active_file,
            "message_count": len(all_messages),
            "upstream_conversation_id": upstream_conversation_id,
            "archived": False,
        },
    )

    save_agent_index(
        dev_repo_root,
        book_id,
        session_agent,
        {
            "book_id": book_id,
            "agent_key": session_agent,
            "active_conversation_id": conversation_id,
            "conversations": conversations,
        },
    )


def get_agent_context(
    dev_repo_root: str | Path | None,
    *,
    book_id: str,
    agent_key: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    session_agent = route_agent_to_session_agent(agent_key)
    index_payload = load_agent_index(dev_repo_root, book_id, session_agent)
    selected_conversation_id = conversation_id or index_payload.get("active_conversation_id")
    messages: list[dict[str, Any]] = []
    if isinstance(selected_conversation_id, str) and selected_conversation_id.strip():
        messages = read_conversation_messages(dev_repo_root, book_id, session_agent, selected_conversation_id.strip())
    return {
        "book_id": book_id,
        "agent_key": session_agent,
        "active_conversation_id": index_payload.get("active_conversation_id"),
        "conversation_id": selected_conversation_id,
        "upstream_conversation_id": _selected_upstream_conversation_id(
            list(index_payload.get("conversations", [])),
            selected_conversation_id,
        ),
        "conversations": _normalize_visible_conversations(index_payload.get("conversations", [])),
        "messages": messages,
    }
