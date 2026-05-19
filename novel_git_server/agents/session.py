from __future__ import annotations

from typing import Callable

from flask import Blueprint, jsonify, request

from utils.session_runtime import (
    activate_conversation,
    archive_conversation,
    create_conversation,
    delete_conversation,
    get_agent_context,
    rename_conversation,
    route_agent_to_session_agent,
)


def create_blueprint(
    *,
    dev_repo_root: str,
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("session", __name__)

    @bp.get("/api/conversations/context")
    def get_conversation_context():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        raw_agent = request.args.get("agent", "")
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
        except ValueError:
            return json_error("INVALID_AGENT", f"unsupported agent: {raw_agent}", 400)

        raw_conversation_id = request.args.get("conversation_id")
        conversation_id = raw_conversation_id.strip() if isinstance(raw_conversation_id, str) and raw_conversation_id.strip() else None

        payload = get_agent_context(
            dev_repo_root,
            book_id=book_id,
            agent_key=agent_key,
            conversation_id=conversation_id,
        )
        return jsonify({"status": "success", **payload}), 200

    @bp.post("/api/conversations/create")
    def create_conversation_route():
        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_agent = payload.get("agent", "")
        raw_active_file = payload.get("active_file", "")
        raw_title = payload.get("title")
        if not isinstance(raw_active_file, str) or not raw_active_file.strip():
            return json_error("INVALID_PAYLOAD", "active_file is required", 400)
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
            result = create_conversation(
                dev_repo_root,
                book_id=book_id,
                agent_key=agent_key,
                active_file=raw_active_file.strip(),
                title=raw_title if isinstance(raw_title, str) else None,
            )
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)
        return jsonify({"status": "success", **result}), 200

    @bp.post("/api/conversations/activate")
    def activate_conversation_route():
        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_agent = payload.get("agent", "")
        raw_conversation_id = payload.get("conversation_id", "")
        if not isinstance(raw_conversation_id, str) or not raw_conversation_id.strip():
            return json_error("INVALID_PAYLOAD", "conversation_id is required", 400)
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
            result = activate_conversation(
                dev_repo_root,
                book_id=book_id,
                agent_key=agent_key,
                conversation_id=raw_conversation_id.strip(),
            )
        except ValueError:
            return json_error("NOT_FOUND", "conversation_not_found", 404)
        return jsonify({"status": "success", **result}), 200

    @bp.post("/api/conversations/rename")
    def rename_conversation_route():
        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_agent = payload.get("agent", "")
        raw_conversation_id = payload.get("conversation_id", "")
        raw_title = payload.get("title", "")
        if not isinstance(raw_conversation_id, str) or not raw_conversation_id.strip():
            return json_error("INVALID_PAYLOAD", "conversation_id is required", 400)
        if not isinstance(raw_title, str) or not raw_title.strip():
            return json_error("INVALID_PAYLOAD", "title is required", 400)
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
            result = rename_conversation(
                dev_repo_root,
                book_id=book_id,
                agent_key=agent_key,
                conversation_id=raw_conversation_id.strip(),
                title=raw_title.strip(),
            )
        except ValueError:
            return json_error("NOT_FOUND", "conversation_not_found", 404)
        return jsonify({"status": "success", **result}), 200

    @bp.post("/api/conversations/archive")
    def archive_conversation_route():
        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_agent = payload.get("agent", "")
        raw_conversation_id = payload.get("conversation_id", "")
        if not isinstance(raw_conversation_id, str) or not raw_conversation_id.strip():
            return json_error("INVALID_PAYLOAD", "conversation_id is required", 400)
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
            result = archive_conversation(
                dev_repo_root,
                book_id=book_id,
                agent_key=agent_key,
                conversation_id=raw_conversation_id.strip(),
            )
        except ValueError:
            return json_error("NOT_FOUND", "conversation_not_found", 404)
        return jsonify({"status": "success", **result}), 200

    @bp.post("/api/conversations/delete")
    def delete_conversation_route():
        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_agent = payload.get("agent", "")
        raw_conversation_id = payload.get("conversation_id", "")
        if not isinstance(raw_conversation_id, str) or not raw_conversation_id.strip():
            return json_error("INVALID_PAYLOAD", "conversation_id is required", 400)
        try:
            agent_key = route_agent_to_session_agent(raw_agent)
            result = delete_conversation(
                dev_repo_root,
                book_id=book_id,
                agent_key=agent_key,
                conversation_id=raw_conversation_id.strip(),
            )
        except ValueError:
            return json_error("NOT_FOUND", "conversation_not_found", 404)
        return jsonify({"status": "success", **result}), 200

    return bp
