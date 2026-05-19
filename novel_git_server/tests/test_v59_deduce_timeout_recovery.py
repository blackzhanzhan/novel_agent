import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.dify_client import DifyClientError  # noqa: E402


class V59DeduceTimeoutRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v59_deduce_timeout_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

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

    def _init_book(self, *, book_name: str) -> str:
        resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()["book_id"]

    def _snapshot_map(self, world_snapshot: dict) -> dict[str, dict]:
        unchanged = {
            "exists": False,
            "commit_id": None,
            "content": "",
            "etag": "etag-unchanged",
        }
        return {
            "domain_rules.md": dict(unchanged),
            "status_card.md": dict(unchanged),
            "world_model.md": world_snapshot,
        }

    @patch("agents.world_draft._draft_file_snapshots")
    @patch("agents.world_draft.chat_messages_stream")
    def test_timeout_after_draft_write_recovers_to_draft_ready_and_done(self, mock_stream, mock_snapshots):
        book_id = self._init_book(book_name="v59_timeout_recovery")

        def failing_stream(*args, **kwargs):
            yield {
                "event": "message",
                "data": {
                    "event": "message",
                    "answer": "initializing",
                    "conversation_id": "conv-timeout-1",
                },
            }
            raise DifyClientError("Dify API request timed out")

        mock_stream.side_effect = failing_stream
        mock_snapshots.side_effect = [
            self._snapshot_map(
                {
                    "exists": False,
                    "commit_id": None,
                    "content": "",
                    "etag": "etag-before",
                }
            ),
            self._snapshot_map(
                {
                    "exists": True,
                    "commit_id": "draft-commit-001",
                    "content": "# World Model\n\nDraft write completed.\n",
                    "etag": "etag-after",
                }
            ),
        ]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "init world model",
                "active_file": "world_model.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        event_names = [event["event"] for event in events]
        self.assertIn("ack", event_names)
        self.assertIn("delta", event_names)
        self.assertIn("draft_ready", event_names)
        self.assertIn("done", event_names)
        self.assertNotIn("error", event_names)

        draft_ready = next(event for event in events if event["event"] == "draft_ready")
        self.assertEqual(draft_ready["data"].get("commit_id"), "draft-commit-001")
        self.assertIn("Draft write completed.", draft_ready["data"].get("content", ""))

        done_event = next(event for event in events if event["event"] == "done")
        self.assertTrue(done_event["data"].get("draft_changed"))
        self.assertFalse(done_event["data"].get("write_confirmed"))
        self.assertEqual(done_event["data"].get("sync_status"), "timeout_after_write")
        self.assertIn("timed out", done_event["data"].get("sync_message", ""))

    @patch("agents.world_draft._draft_file_snapshots")
    @patch("agents.world_draft.chat_messages_stream")
    def test_timeout_without_draft_write_still_emits_error(self, mock_stream, mock_snapshots):
        book_id = self._init_book(book_name="v59_timeout_no_write")

        def failing_stream(*args, **kwargs):
            yield {
                "event": "message",
                "data": {
                    "event": "message",
                    "answer": "initializing",
                    "conversation_id": "conv-timeout-2",
                },
            }
            raise DifyClientError("Dify API request timed out")

        mock_stream.side_effect = failing_stream
        unchanged_world = {
            "exists": False,
            "commit_id": None,
            "content": "",
            "etag": "etag-before",
        }
        mock_snapshots.side_effect = [
            self._snapshot_map(dict(unchanged_world)),
            self._snapshot_map(dict(unchanged_world)),
        ]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "init world model",
                "active_file": "world_model.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        event_names = [event["event"] for event in events]
        self.assertIn("ack", event_names)
        self.assertIn("delta", event_names)
        self.assertIn("error", event_names)
        self.assertNotIn("draft_ready", event_names)

        error_event = next(event for event in events if event["event"] == "error")
        self.assertEqual(error_event["data"].get("code"), "DIFY_API_FAILED")
        self.assertIn("timed out", error_event["data"].get("message", ""))

    @patch("agents.world_draft._draft_file_snapshots")
    @patch("agents.world_draft.chat_messages_stream")
    def test_normal_completion_with_draft_change_emits_draft_ready(self, mock_stream, mock_snapshots):
        book_id = self._init_book(book_name="v59_normal_draft_ready")

        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "done",
                        "conversation_id": "conv-success-1",
                    },
                }
            ]
        )
        mock_snapshots.side_effect = [
            self._snapshot_map(
                {
                    "exists": False,
                    "commit_id": None,
                    "content": "",
                    "etag": "etag-before",
                }
            ),
            self._snapshot_map(
                {
                    "exists": True,
                    "commit_id": "draft-commit-002",
                    "content": "# World Model\n\nNormal draft write.\n",
                    "etag": "etag-after",
                }
            ),
        ]

        resp = self.client.post(
            f"/api/world/deduce_stream?book_id={book_id}",
            json={
                "intent": "init world model",
                "active_file": "world_model.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        event_names = [event["event"] for event in events]
        self.assertIn("draft_ready", event_names)
        self.assertIn("done", event_names)
        self.assertNotIn("error", event_names)

        draft_ready = next(event for event in events if event["event"] == "draft_ready")
        self.assertEqual(draft_ready["data"].get("commit_id"), "draft-commit-002")
        self.assertIn("Normal draft write.", draft_ready["data"].get("content", ""))

        done_event = next(event for event in events if event["event"] == "done")
        self.assertTrue(done_event["data"].get("draft_changed"))
        self.assertTrue(done_event["data"].get("write_confirmed"))


if __name__ == "__main__":
    unittest.main()
