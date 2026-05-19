from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://frontend:5173").rstrip("/")
DIFY_SMOKE_URL = os.environ.get("DIFY_SMOKE_URL", "").strip()
DIFY_SMOKE_REQUIRED = os.environ.get("DIFY_SMOKE_REQUIRED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}


def fetch(url: str, timeout: int = 10) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "novel-agent-compose-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.status), body, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), body, ""
    except Exception as exc:
        return 0, "", str(exc)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    results: dict[str, object] = {}

    status, body, error = fetch(f"{BACKEND_URL}/health")
    assert_ok(status == 200, f"backend health failed: status={status} error={error}")
    backend_json = json.loads(body)
    assert_ok(backend_json.get("status") == "ok", f"backend health payload invalid: {backend_json}")
    results["backend"] = backend_json

    status, body, error = fetch(FRONTEND_URL)
    assert_ok(status == 200, f"frontend root failed: status={status} error={error}")
    assert_ok("LoreGit" in body or "Causal" in body, "frontend root does not look like the demo UI")
    results["frontend_root_status"] = status

    proxy_url = f"{FRONTEND_URL}/books/ping?{urllib.parse.urlencode({'book_id': '_compose_smoke'})}"
    status, body, error = fetch(proxy_url)
    assert_ok(status in {200, 400, 404}, f"frontend proxy failed: status={status} error={error}")
    results["frontend_proxy_status"] = status

    if DIFY_SMOKE_URL:
        status, body, error = fetch(DIFY_SMOKE_URL)
        if DIFY_SMOKE_REQUIRED:
            assert_ok(status in {200, 204, 301, 302}, f"Dify smoke failed: status={status} error={error}")
            results["dify"] = {"status": status, "required": True}
        else:
            results["dify"] = {"status": status, "required": False}
    else:
        results["dify"] = {"status": "skipped", "required": DIFY_SMOKE_REQUIRED}
        assert_ok(not DIFY_SMOKE_REQUIRED, "Dify smoke required but DIFY_SMOKE_URL is empty")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
