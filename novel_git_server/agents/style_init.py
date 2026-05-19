from __future__ import annotations

import json as _json
import os
import threading
from queue import Empty, Queue
from typing import Any, Callable

from flask import Blueprint, Response, request, stream_with_context


def _coerce_positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def _validate_markdown_file_name(book_dir: str, raw_file_name: Any) -> tuple[str | None, str | None]:
    file_name = str(raw_file_name or "chapter_draft.md").strip().replace("\\", "/")
    if not file_name:
        return None, "draft_file must be a non-empty string"
    if file_name.startswith("/") or file_name.startswith("../") or "/../" in file_name or file_name == "..":
        return None, "draft_file must stay inside the book directory"
    if not file_name.lower().endswith(".md"):
        return None, "draft_file must point to a markdown file"
    abs_book_dir = os.path.abspath(book_dir)
    abs_path = os.path.abspath(os.path.join(abs_book_dir, file_name))
    if os.path.commonpath([abs_path, abs_book_dir]) != abs_book_dir:
        return None, "draft_file must stay inside the book directory"
    return file_name, None


def create_blueprint(
    *,
    storage_root: str,
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("style_init", __name__)

    @bp.post("/api/style/init_pipeline")
    def init_style_pipeline():
        from utils.book_storage import get_book_paths
        from pipelines.style_artifact_init import run_pipeline

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return json_error("INVALID_PAYLOAD", "request body must be application/json object", 400)

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        assert book_id is not None

        paths = get_book_paths(book_id, storage_root)
        if not os.path.isdir(paths["book_dir"]):
            return json_error("BOOK_NOT_FOUND", "book not found", 404)

        source_count = _coerce_positive_int(payload.get("source_count"), 12, 30)
        draft_file = payload.get("draft_file") or "chapter_draft.md"
        draft_file, draft_file_err = _validate_markdown_file_name(paths["book_dir"], draft_file)
        if draft_file_err:
            return json_error("INVALID_PAYLOAD", draft_file_err, 400)
        assert draft_file is not None
        force_rebuild = payload.get("force_rebuild") is True
        sse_queue: Queue = Queue()

        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

        def generate():
            def _run():
                try:
                    run_pipeline(
                        book_id=book_id,
                        book_dir=paths["book_dir"],
                        sse_queue=sse_queue,
                        source_count=source_count,
                        draft_file=draft_file,
                        draft_chapters=payload.get("draft_chapters"),
                        force_rebuild=force_rebuild,
                    )
                except Exception as exc:
                    sse_queue.put({"event": "error", "data": {"message": str(exc)}})

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

            try:
                while thread.is_alive() or not sse_queue.empty():
                    try:
                        evt = sse_queue.get(timeout=1.0)
                        yield _sse(evt["event"], evt["data"])
                    except Empty:
                        continue
            except GeneratorExit:
                pass
            finally:
                yield _sse("pipeline_end", {})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return bp
