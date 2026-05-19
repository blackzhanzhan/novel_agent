from __future__ import annotations

import os
from typing import Callable

from flask import Blueprint, jsonify, current_app, request

from utils.dify_registry import build_dify_agent_registry
from utils.model_provider import build_batch_model_config
from utils.runtime_config import (
    apply_runtime_updates_to_process_env,
    build_runtime_config_view,
    coerce_timeout_seconds,
    normalize_runtime_config_updates,
    write_runtime_config_file,
)


def create_blueprint(
    *,
    config_dir: str,
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("runtime_config", __name__)
    config_dir = os.path.abspath(config_dir)

    def _redacted_view() -> dict:
        return build_runtime_config_view(config_dir)

    def _refresh_app_runtime_config() -> None:
        app = current_app._get_current_object()
        app.config["DIFY_BASE_URL"] = os.environ.get("DIFY_BASE_URL", "http://localhost/v1").rstrip("/")
        app.config["DIFY_API_KEY"] = os.environ.get("DIFY_API_KEY", "").strip()
        app.config["DIFY_TIMEOUT_SECONDS"] = coerce_timeout_seconds(
            os.environ.get("DIFY_TIMEOUT_SECONDS", "90"),
            default=90,
        )
        refreshed_registry = build_dify_agent_registry(
            default_base_url=app.config["DIFY_BASE_URL"],
            default_api_key=app.config["DIFY_API_KEY"],
            default_timeout_seconds=app.config["DIFY_TIMEOUT_SECONDS"],
            agent_keys=("continuation_agent", "review_agent", "world_model", "style_guide", "outline"),
        )
        registry = app.config.setdefault("DIFY_AGENT_REGISTRY", {})
        registry.clear()
        registry.update(refreshed_registry)

    @bp.get("/api/runtime/config")
    def get_runtime_config():
        return jsonify({"status": "success", **_redacted_view()}), 200

    @bp.get("/api/runtime/config/check")
    def check_runtime_config():
        view = _redacted_view()
        model_config = build_batch_model_config()
        model_key = "OPENAI_COMPATIBLE_API_KEY" if model_config.provider == "openai_compatible" else "DEEPSEEK_API_KEY"
        missing_required = [
            key
            for key in (
                "DIFY_WORLD_MODEL_API_KEY",
                "DIFY_STYLE_GUIDE_API_KEY",
                "DIFY_OUTLINE_API_KEY",
                "DIFY_CONTINUATION_API_KEY",
                "DIFY_REVIEW_API_KEY",
                model_key,
            )
            if not view["config"].get(key, {}).get("configured")
        ]
        return (
            jsonify(
                {
                    "status": "success",
                    "ready": not missing_required,
                    "missing_required_keys": missing_required,
                    "groups": view["groups"],
                }
            ),
            200,
        )

    @bp.post("/api/runtime/config")
    def save_runtime_config():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return json_error("INVALID_PAYLOAD", "request body must be application/json", 400)
        updates, errors = normalize_runtime_config_updates(payload.get("values"))
        if errors:
            return jsonify({"status": "error", "code": "INVALID_CONFIG", "errors": errors}), 400

        write_runtime_config_file(config_dir, updates)
        apply_runtime_updates_to_process_env(updates)
        _refresh_app_runtime_config()

        return (
            jsonify(
                {
                    "status": "success",
                    "saved_keys": sorted(updates.keys()),
                    **_redacted_view(),
                }
            ),
            200,
        )

    return bp
