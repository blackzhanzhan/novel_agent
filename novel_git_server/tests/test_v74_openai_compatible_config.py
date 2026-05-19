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
from utils.model_provider import build_batch_model_config  # noqa: E402
from utils.runtime_config import parse_env_file  # noqa: E402


class V74OpenAICompatibleConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v74_oai_config_{uuid.uuid4().hex}"
        self.storage_dir = self.temp_dir / "storage"
        self.config_dir = self.temp_dir / "config"
        self.dev_repo_dir = self.temp_dir / "dev_repo"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dev_repo_dir.mkdir(parents=True, exist_ok=True)
        self._saved_env = {
            key: os.environ.get(key)
            for key in [
                "MODEL_PROVIDER",
                "OPENAI_COMPATIBLE_BASE_URL",
                "OPENAI_COMPATIBLE_API_KEY",
                "OPENAI_COMPATIBLE_MODEL",
                "OPENAI_BASE_URL",
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "DEEPSEEK_BASE_URL",
                "DEEPSEEK_API_KEY",
                "DEEPSEEK_MODEL",
                "SUMMARY_ARCHIVE_MODEL",
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

    def test_runtime_config_saves_openai_compatible_fields_without_echoing_key(self):
        secret = "openai-compatible-secret-xyz987"
        resp = self.client.post(
            "/api/runtime/config",
            json={
                "values": {
                    "MODEL_PROVIDER": "openai_compatible",
                    "OPENAI_COMPATIBLE_BASE_URL": "https://gateway.example.com/v1",
                    "OPENAI_COMPATIBLE_MODEL": "third-party-flash",
                    "OPENAI_COMPATIBLE_API_KEY": secret,
                }
            },
        )
        self.assertEqual(resp.status_code, 200)
        raw_body = self._raw_json(resp)

        self.assertNotIn(secret, raw_body)
        self.assertIn("****z987", raw_body)
        body = resp.get_json()
        self.assertEqual(body["config"]["MODEL_PROVIDER"]["value"], "openai_compatible")
        self.assertEqual(body["config"]["OPENAI_COMPATIBLE_BASE_URL"]["value"], "https://gateway.example.com/v1")
        self.assertTrue(body["config"]["OPENAI_COMPATIBLE_API_KEY"]["configured"])

        parsed = parse_env_file(self.config_dir)
        self.assertEqual(parsed["MODEL_PROVIDER"], "openai_compatible")
        self.assertEqual(parsed["OPENAI_COMPATIBLE_API_KEY"], secret)

    def test_runtime_config_check_requires_selected_provider_key(self):
        resp = self.client.post(
            "/api/runtime/config",
            json={
                "values": {
                    "MODEL_PROVIDER": "openai_compatible",
                    "OPENAI_COMPATIBLE_BASE_URL": "https://gateway.example.com/v1",
                    "OPENAI_COMPATIBLE_MODEL": "third-party-flash",
                }
            },
        )
        self.assertEqual(resp.status_code, 200)

        check_resp = self.client.get("/api/runtime/config/check")
        self.assertEqual(check_resp.status_code, 200)
        missing = check_resp.get_json()["missing_required_keys"]
        self.assertIn("OPENAI_COMPATIBLE_API_KEY", missing)
        self.assertNotIn("DEEPSEEK_API_KEY", missing)

    def test_runtime_config_check_auto_detects_openai_compatible_signal(self):
        resp = self.client.post(
            "/api/runtime/config",
            json={
                "values": {
                    "OPENAI_COMPATIBLE_BASE_URL": "https://gateway.example.com/v1",
                    "OPENAI_COMPATIBLE_MODEL": "third-party-flash",
                }
            },
        )
        self.assertEqual(resp.status_code, 200)

        check_resp = self.client.get("/api/runtime/config/check")
        self.assertEqual(check_resp.status_code, 200)
        missing = check_resp.get_json()["missing_required_keys"]
        self.assertIn("OPENAI_COMPATIBLE_API_KEY", missing)
        self.assertNotIn("DEEPSEEK_API_KEY", missing)

    def test_model_provider_uses_openai_compatible_config(self):
        config = build_batch_model_config(
            env={
                "MODEL_PROVIDER": "openai_compatible",
                "OPENAI_COMPATIBLE_BASE_URL": "https://gateway.example.com/v1",
                "OPENAI_COMPATIBLE_API_KEY": "secret",
                "OPENAI_COMPATIBLE_MODEL": "third-party-flash",
            },
            purpose="world_model_init",
        )

        self.assertEqual(config.provider, "openai_compatible")
        self.assertEqual(config.base_url, "https://gateway.example.com/v1")
        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.model, "third-party-flash")

    def test_model_provider_uses_openai_compatible_default_base_url(self):
        config = build_batch_model_config(
            env={
                "MODEL_PROVIDER": "openai_compatible",
                "OPENAI_COMPATIBLE_API_KEY": "secret",
                "OPENAI_COMPATIBLE_MODEL": "third-party-flash",
            },
            purpose="world_model_init",
        )

        self.assertEqual(config.provider, "openai_compatible")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")

    def test_model_provider_preserves_legacy_deepseek_config(self):
        config = build_batch_model_config(
            env={
                "DEEPSEEK_BASE_URL": "https://api.deepseek.example",
                "DEEPSEEK_API_KEY": "deepseek-secret",
                "DEEPSEEK_MODEL": "deepseek-chat",
            },
            purpose="world_model_init",
        )

        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.base_url, "https://api.deepseek.example")
        self.assertEqual(config.api_key, "deepseek-secret")
        self.assertEqual(config.model, "deepseek-chat")

    def test_summary_archive_model_override_applies_to_openai_compatible(self):
        config = build_batch_model_config(
            env={
                "MODEL_PROVIDER": "openai_compatible",
                "OPENAI_COMPATIBLE_BASE_URL": "https://gateway.example.com/v1",
                "OPENAI_COMPATIBLE_API_KEY": "secret",
                "OPENAI_COMPATIBLE_MODEL": "default-model",
                "SUMMARY_ARCHIVE_MODEL": "summary-special",
            },
            purpose="summary_archive",
        )

        self.assertEqual(config.provider, "openai_compatible")
        self.assertEqual(config.model, "summary-special")

    def test_invalid_model_provider_is_rejected_without_partial_file(self):
        resp = self.client.post(
            "/api/runtime/config",
            json={"values": {"MODEL_PROVIDER": "unknown-provider", "OPENAI_COMPATIBLE_API_KEY": "should-not-write"}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse((self.config_dir / ".env.local").exists())


if __name__ == "__main__":
    unittest.main()
