import os
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

from agents import archive, chapter, checkout, git_console, history, library, rolling, runtime_config, session, style_init, summary, tomato_import, tools, world_draft, world_state
from utils.book_storage import get_book_paths, get_storage_root, inspect_book_layout_integrity, resolve_book_id, resolve_book_locators
from utils.dify_registry import build_dify_agent_registry


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_ROUTES = {"/save_outline", "/outlines", "/commit", "/history", "/world_model"}
DEDUCE_FILE_TYPES = ("world_core", "summary", "outline", "style", "chapter", "error_archive")


def _load_local_env(base_dir: str, filename: str = ".env.local", *, override: bool = True) -> None:
    env_path = os.path.join(base_dir, filename)
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = raw_value.strip().strip('"').strip("'")
            if override or key not in os.environ:
                os.environ[key] = value


_load_local_env(BASE_DIR)


def create_app(
    storage_root: str | None = None,
    dev_repo_root: str | None = None,
    runtime_config_dir: str | None = None,
) -> Flask:
    app = Flask(__name__)
    CORS(app)
    app.json.ensure_ascii = False

    resolved_storage_root = os.path.abspath(storage_root or get_storage_root(BASE_DIR))
    app.config["STORAGE_ROOT"] = resolved_storage_root
    app.config["RUNTIME_CONFIG_DIR"] = os.path.abspath(runtime_config_dir or BASE_DIR)
    if runtime_config_dir is not None:
        _load_local_env(app.config["RUNTIME_CONFIG_DIR"])
    app.config["DEV_REPO_ROOT"] = os.path.abspath(
        dev_repo_root
        or os.environ.get("CHRONOS_DEV_REPO_ROOT", os.path.join(os.path.dirname(BASE_DIR), "dev_repo"))
    )
    app.config["DATABASE_JSON_RETIRED"] = True
    app.config["DIFY_BASE_URL"] = os.environ.get("DIFY_BASE_URL", "http://localhost/v1").rstrip("/")
    app.config["DIFY_API_KEY"] = os.environ.get("DIFY_API_KEY", "").strip()
    app.config["DIFY_TIMEOUT_SECONDS"] = int(os.environ.get("DIFY_TIMEOUT_SECONDS", "90"))
    app.config["DIFY_AGENT_REGISTRY"] = build_dify_agent_registry(
        default_base_url=app.config["DIFY_BASE_URL"],
        default_api_key=app.config["DIFY_API_KEY"],
        default_timeout_seconds=app.config["DIFY_TIMEOUT_SECONDS"],
        agent_keys=("continuation_agent", "review_agent", "world_model", "style_guide", "outline"),
    )

    def json_error(code: str, message: str, status_code: int = 400):
        return jsonify({"status": "error", "code": code, "message": message}), status_code

    def parse_json_payload(required_fields: list[str] | None = None) -> tuple[dict[str, Any] | None, tuple | None]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return None, json_error("INVALID_PAYLOAD", "request body must be application/json", 400)
        if required_fields:
            missing = [field for field in required_fields if field not in payload]
            if missing:
                return None, json_error("MISSING_FIELD", f"missing fields: {', '.join(missing)}", 400)
        return payload, None

    def require_book_id(payload: dict[str, Any] | None = None) -> tuple[str | None, tuple | None]:
        raw_book_id: Any = None
        raw_book_name: Any = None
        if isinstance(payload, dict):
            raw_book_id = payload.get("book_id")
            raw_book_name = payload.get("book_name")
        if raw_book_id is None:
            raw_book_id = request.args.get("book_id")
        if raw_book_name is None:
            raw_book_name = request.args.get("book_name")
        try:
            resolved_book_id, resolved_book_name_id = resolve_book_locators(
                raw_book_id,
                raw_book_name,
                app.config["STORAGE_ROOT"],
            )
            if resolved_book_id and resolved_book_name_id and resolved_book_id != resolved_book_name_id:
                return None, json_error(
                    "BOOK_LOCATOR_CONFLICT",
                    (
                        "book_id conflicts with book_name resolution; "
                        f"book_id={resolved_book_id}, book_name_resolved={resolved_book_name_id}. "
                        "For write flows, send only book_id."
                    ),
                    409,
                )
            return resolve_book_id(raw_book_id, raw_book_name, app.config["STORAGE_ROOT"]), None
        except ValueError as exc:
            return None, json_error("MISSING_FIELD", str(exc), 400)

    app.extensions["chronos_helpers"] = {
        "json_error": json_error,
        "parse_json_payload": parse_json_payload,
        "require_book_id": require_book_id,
    }

    @app.get("/health")
    def health() -> tuple:
        return (
            jsonify(
                {
                    "status": "ok",
                    "service": "chronos-v3",
                    "database_json": "retired" if app.config.get("DATABASE_JSON_RETIRED") else "active",
                }
            ),
            200,
        )

    @app.get("/books/ping")
    def books_ping():
        book_id, err = require_book_id()
        if err:
            return err
        paths = get_book_paths(book_id, app.config["STORAGE_ROOT"])
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "book_dir": paths["book_dir"],
                    "integrity": inspect_book_layout_integrity(book_id, app.config["STORAGE_ROOT"]),
                }
            ),
            200,
        )

    app.register_blueprint(
        library.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        runtime_config.create_blueprint(
            config_dir=app.config["RUNTIME_CONFIG_DIR"],
            json_error=json_error,
        )
    )
    app.register_blueprint(
        chapter.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        tomato_import.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
            dify_agent_registry=app.config.get("DIFY_AGENT_REGISTRY"),
        )
    )
    app.register_blueprint(
        world_state.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        world_draft.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            dev_repo_root=app.config["DEV_REPO_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
            dify_base_url=app.config["DIFY_BASE_URL"],
            dify_api_key=app.config["DIFY_API_KEY"],
            dify_timeout_seconds=app.config["DIFY_TIMEOUT_SECONDS"],
            dify_agent_registry=app.config["DIFY_AGENT_REGISTRY"],
        )
    )
    app.register_blueprint(
        summary.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        tools.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        style_init.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        rolling.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        checkout.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        history.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        session.create_blueprint(
            dev_repo_root=app.config["DEV_REPO_ROOT"],
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        git_console.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )
    app.register_blueprint(
        archive.create_blueprint(
            storage_root=app.config["STORAGE_ROOT"],
            parse_json_payload=parse_json_payload,
            require_book_id=require_book_id,
            json_error=json_error,
        )
    )

    active_routes = {rule.rule for rule in app.url_map.iter_rules()}
    leaked_routes = sorted(route for route in LEGACY_ROUTES if route in active_routes)
    if leaked_routes:
        raise RuntimeError(f"legacy routes are forbidden in v3: {', '.join(leaked_routes)}")

    return app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    app.run(host=host, port=port, threaded=True)
