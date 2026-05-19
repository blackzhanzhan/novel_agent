import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.runtime_config import parse_env_file  # noqa: E402


class V73RuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v73_runtime_config_{uuid.uuid4().hex}"
        self.storage_dir = self.temp_dir / "storage"
        self.config_dir = self.temp_dir / "config"
        self.dev_repo_dir = self.temp_dir / "dev_repo"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dev_repo_dir.mkdir(parents=True, exist_ok=True)
        self._saved_env = {
            key: os.environ.get(key)
            for key in [
                "DIFY_BASE_URL",
                "DIFY_TIMEOUT_SECONDS",
                "DIFY_API_KEY",
                "DIFY_WORLD_MODEL_API_KEY",
                "DIFY_WORLD_CORE_API_KEY",
                "DIFY_STYLE_GUIDE_API_KEY",
                "DIFY_STYLE_API_KEY",
                "DIFY_OUTLINE_API_KEY",
                "DIFY_CONTINUATION_API_KEY",
                "DIFY_REVIEW_API_KEY",
                "MODEL_PROVIDER",
                "OPENAI_COMPATIBLE_BASE_URL",
                "OPENAI_COMPATIBLE_API_KEY",
                "OPENAI_COMPATIBLE_MODEL",
                "OPENAI_BASE_URL",
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "DEEPSEEK_API_KEY",
            ]
        }
        for key in self._saved_env:
            os.environ.pop(key, None)
        self.app = gs.create_app(
            storage_root=str(self.storage_dir),
            dev_repo_root=str(self.dev_repo_dir),
            runtime_config_dir=str(self.config_dir),
        )
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _raw_json(self, response) -> str:
        return json.dumps(response.get_json(), ensure_ascii=False, sort_keys=True)

    def test_missing_env_local_returns_safe_redacted_default_view(self):
        resp = self.client.get("/api/runtime/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        self.assertFalse(body["env_file_exists"])
        self.assertEqual(body["config"]["DIFY_BASE_URL"]["value"], "http://localhost/v1")
        self.assertEqual(body["config"]["DIFY_BASE_URL"]["source"], "default")
        self.assertFalse(body["config"]["DIFY_CONTINUATION_API_KEY"]["configured"])
        self.assertNotIn("api-key", self._raw_json(resp).lower())

    def test_save_runtime_config_writes_env_file_and_never_echoes_secret(self):
        secret = "dify-continuation-secret-123456"
        resp = self.client.post(
            "/api/runtime/config",
            json={
                "values": {
                    "DIFY_BASE_URL": "http://localhost/v1",
                    "DIFY_TIMEOUT_SECONDS": "123",
                    "DIFY_CONTINUATION_API_KEY": secret,
                    "DEEPSEEK_API_KEY": "deepseek-secret-abcdef",
                }
            },
        )
        self.assertEqual(resp.status_code, 200)
        raw_body = self._raw_json(resp)

        self.assertNotIn(secret, raw_body)
        self.assertIn("****3456", raw_body)
        self.assertTrue((self.config_dir / ".env.local").exists())
        parsed = parse_env_file(self.config_dir)
        self.assertEqual(parsed["DIFY_CONTINUATION_API_KEY"], secret)
        self.assertEqual(parsed["DIFY_TIMEOUT_SECONDS"], "123")

    def test_save_runtime_config_hot_refreshes_existing_registry_object(self):
        registry_before = self.app.config["DIFY_AGENT_REGISTRY"]
        old_route = registry_before["continuation_agent"]
        self.assertEqual(old_route.api_key, "")

        secret = "hot-refresh-continuation-key"
        resp = self.client.post(
            "/api/runtime/config",
            json={
                "values": {
                    "DIFY_BASE_URL": "http://127.0.0.1:8080/v1",
                    "DIFY_TIMEOUT_SECONDS": "77",
                    "DIFY_CONTINUATION_API_KEY": secret,
                }
            },
        )
        self.assertEqual(resp.status_code, 200)

        registry_after = self.app.config["DIFY_AGENT_REGISTRY"]
        self.assertIs(registry_before, registry_after)
        refreshed_route = registry_after["continuation_agent"]
        self.assertEqual(refreshed_route.api_key, secret)
        self.assertEqual(refreshed_route.base_url, "http://127.0.0.1:8080/v1")
        self.assertEqual(refreshed_route.timeout_seconds, 77)

    def test_create_app_loads_runtime_config_dir_env_file(self):
        (self.config_dir / ".env.local").write_text(
            "\n".join(
                [
                    "DIFY_BASE_URL=http://127.0.0.1:9090/v1",
                    "DIFY_TIMEOUT_SECONDS=66",
                    "DIFY_CONTINUATION_API_KEY=restarted-continuation-key",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        restarted_app = gs.create_app(
            storage_root=str(self.storage_dir),
            dev_repo_root=str(self.dev_repo_dir),
            runtime_config_dir=str(self.config_dir),
        )
        route = restarted_app.config["DIFY_AGENT_REGISTRY"]["continuation_agent"]
        self.assertEqual(route.api_key, "restarted-continuation-key")
        self.assertEqual(route.base_url, "http://127.0.0.1:9090/v1")
        self.assertEqual(route.timeout_seconds, 66)

    def test_save_runtime_config_rejects_invalid_timeout_without_partial_file(self):
        resp = self.client.post(
            "/api/runtime/config",
            json={"values": {"DIFY_TIMEOUT_SECONDS": "0", "DIFY_CONTINUATION_API_KEY": "should-not-write"}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse((self.config_dir / ".env.local").exists())

    def test_runtime_config_check_reports_missing_required_keys(self):
        resp = self.client.get("/api/runtime/config/check")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        self.assertFalse(body["ready"])
        self.assertIn("DIFY_CONTINUATION_API_KEY", body["missing_required_keys"])
        self.assertIn("DEEPSEEK_API_KEY", body["missing_required_keys"])


if __name__ == "__main__":
    unittest.main()
