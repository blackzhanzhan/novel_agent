import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V60DifyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v60_dify_registry_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_local_env_overrides_stale_parent_dify_keys(self):
        key = "DIFY_CONTINUATION_API_KEY"
        previous = os.environ.get(key)
        try:
            (self.temp_dir / ".env.local").write_text(f"{key}=file-local-key\n", encoding="utf-8")
            os.environ[key] = "stale-parent-key"
            gs._load_local_env(str(self.temp_dir))
            route = gs.create_app(storage_root=str(self.temp_dir)).config["DIFY_AGENT_REGISTRY"]["continuation_agent"]
            self.assertEqual(route.api_key, "file-local-key")
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    def _git(self, repo_dir: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _parse_sse_events(self, raw_stream: str) -> list[dict]:
        events: list[dict] = []
        for chunk in raw_stream.split("\n\n"):
            block = chunk.strip()
            if not block:
                continue
            event_name = "message"
            data_lines: list[str] = []
            for line in block.splitlines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
            raw_data = "\n".join(data_lines)
            data = {}
            if raw_data:
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    data = {"raw": raw_data}
            events.append({"event": event_name, "data": data})
        return events

    def test_app_builds_world_model_registry_entry(self):
        registry = self.app.config["DIFY_AGENT_REGISTRY"]
        self.assertIn("world_model", registry)
        self.assertIn("style_guide", registry)
        self.assertIn("outline", registry)
        self.assertNotIn("reading_archive_agent", registry)
        self.assertEqual(registry["world_model"].routed_agent, "world_model")
        self.assertEqual(registry["style_guide"].routed_agent, "style_guide")
        self.assertEqual(registry["outline"].routed_agent, "outline")

    def test_book_init_creates_style_diagnostic_artifacts(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_style_artifacts"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        repo_dir = self.temp_dir / book_id

        expected_files = [
            "style_fingerprint.md",
            "style_review.md",
            "style_constraints_for_continuation.md",
            "domain_rules.md",
        ]
        for file_name in expected_files:
            self.assertTrue((repo_dir / file_name).exists(), file_name)

        tracked = set(self._git(repo_dir, "ls-files", "--", *expected_files).splitlines())
        self.assertEqual(tracked, set(expected_files))

    def test_style_agent_routes_all_style_diagnostic_artifacts(self):
        route = self.app.config["DIFY_AGENT_REGISTRY"]["style_guide"]

        for file_name in [
            "style_guide.md",
            "style_fingerprint.md",
            "style_review.md",
            "style_constraints_for_continuation.md",
        ]:
            self.assertTrue(route.matches_route_target(file_name), file_name)
            self.assertTrue(route.can_read(file_name), file_name)
            self.assertTrue(route.can_write(file_name), file_name)

        for file_name in ["chapter_draft.md", "world_model.md", "status_card.md"]:
            self.assertFalse(route.can_write(file_name), file_name)

    def test_world_agent_routes_domain_rules_for_generated_rule_maintenance(self):
        route = self.app.config["DIFY_AGENT_REGISTRY"]["world_model"]

        self.assertTrue(route.matches_route_target("domain_rules.md"))
        self.assertTrue(route.can_read("domain_rules.md"))
        self.assertTrue(route.can_write("domain_rules.md"))

    def test_continuation_and_review_can_read_constraints_but_not_write_them(self):
        registry = self.app.config["DIFY_AGENT_REGISTRY"]

        for agent_key in ["continuation_agent", "review_agent"]:
            route = registry[agent_key]
            self.assertTrue(route.can_read("style_constraints_for_continuation.md"))
            self.assertFalse(route.can_write("style_constraints_for_continuation.md"))
            self.assertTrue(route.can_read("domain_rules.md"))
            self.assertFalse(route.can_write("domain_rules.md"))
            self.assertFalse(route.can_read("style_fingerprint.md"))
            self.assertFalse(route.can_read("style_review.md"))

    def test_reading_archive_route_is_retired_from_default_registry(self):
        registry = self.app.config["DIFY_AGENT_REGISTRY"]
        review_route = registry["review_agent"]

        self.assertNotIn("reading_archive_agent", registry)
        self.assertFalse(review_route.can_write("summary.md"))
        self.assertTrue(review_route.can_write("error_archive.md"))

    def test_deduce_stream_ack_uses_world_model_routed_agent(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_world"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "初始化世界观",
                "active_file": "world_model.md",
                "file_type": "world_core",
                "mock_ai_markdown": "mock-world",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "world_model")
        self.assertEqual(ack_event["data"].get("file_type"), "world_core")

    def test_deduce_stream_ack_routes_style_guide_to_style_agent(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_style"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "重建文风指南",
                "active_file": "style_guide.md",
                "file_type": "style",
                "mock_ai_markdown": "mock-style",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "style_guide")
        self.assertEqual(ack_event["data"].get("file_type"), "style")
        self.assertEqual(ack_event["data"].get("write_scope"), "active_file_strict")

    def test_deduce_stream_ack_routes_style_fingerprint_to_style_agent(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_style_fingerprint"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "生成叙事结构指纹",
                "active_file": "style_fingerprint.md",
                "file_type": "style",
                "mock_ai_markdown": "mock-style-fingerprint",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "style_guide")
        self.assertEqual(ack_event["data"].get("file_type"), "style")
        self.assertEqual(ack_event["data"].get("write_scope"), "active_file_strict")

    def test_deduce_stream_ack_routes_outline_file_to_outline_agent(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_outline"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "头脑风暴新主线",
                "active_file": "brainstorm.md",
                "file_type": "outline",
                "mock_ai_markdown": "mock-outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "outline")
        self.assertEqual(ack_event["data"].get("file_type"), "outline")
        self.assertEqual(ack_event["data"].get("write_scope"), "active_file_strict")

    def test_deduce_stream_accepts_session_agent_alias_for_outline_route(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_outline_alias"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "outline alias route smoke",
                "active_file": "brainstorm.md",
                "file_type": "outline",
                "route_agent_key": "outline_agent",
                "mock_ai_markdown": "mock-outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "outline")
        self.assertEqual(ack_event["data"].get("file_type"), "outline")
        self.assertEqual(ack_event["data"].get("write_scope"), "active_file_strict")

    def test_deduce_stream_can_force_chapter_draft_to_review_agent(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_review_bridge"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "Review gate evidence only. Do not write chapter_draft.md.",
                "active_file": "chapter_draft.md",
                "file_type": "chapter",
                "route_agent_key": "review_agent",
                "mock_ai_markdown": "mock-review",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "review_agent")
        self.assertEqual(ack_event["data"].get("file_type"), "chapter")
        self.assertEqual(ack_event["data"].get("write_scope"), "generic")

    def test_deduce_stream_rejects_style_file_type_mismatch(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_style_mismatch"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "错误类型",
                "active_file": "style_guide.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("does not match active_file", body["message"])

    def test_deduce_stream_rejects_outline_file_type_mismatch(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_registry_outline_mismatch"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "错误类型",
                "active_file": "brainstorm.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("does not match active_file", body["message"])

    def test_deduce_stream_auto_repairs_untracked_outline_layout(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v60_outline_layout_heal"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        repo_dir = self.temp_dir / book_id

        self._git(
            repo_dir,
            "rm",
            "--cached",
            "--quiet",
            "--",
            "brainstorm.md",
            "master_outline.md",
            "arc_outline.md",
            "chapter_outline.md",
        )
        self._git(repo_dir, "commit", "-m", "simulate legacy untracked planning files")

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "继续整理头脑风暴",
                "active_file": "brainstorm.md",
                "file_type": "outline",
                "mock_ai_markdown": "mock-outline-heal",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("routed_agent"), "outline")


if __name__ == "__main__":
    unittest.main()
