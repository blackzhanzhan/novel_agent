import json
import os
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


class V46WorldDeduceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v46_world_deduce_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.dev_repo_dir = self.temp_dir / "dev_repo"
        self.app = gs.create_app(storage_root=str(self.temp_dir), dev_repo_root=str(self.dev_repo_dir))
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

    def test_deduce_with_mock_returns_answer_and_conversation_id(self):
        resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": "v46_mock_deduce",
                "intent": "把武器改成精钢长剑",
                "active_file": "world_model.md",
                "mock_ai_markdown": "# ai mock output",
                "conversation_id": "conv-local-001",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["file_name"], "world_model.md")
        self.assertTrue(body["etag"])
        self.assertTrue(isinstance(body["branch"], str) and body["branch"])
        self.assertEqual(body["answer"], "# ai mock output")
        self.assertEqual(body["conversation_id"], "conv-local-001")
        self.assertEqual(body["upstream_conversation_id"], "conv-local-001")

    @patch("agents.world_draft.chat_messages")
    def test_deduce_passes_resolved_book_id_to_dify_inputs(self, mock_chat):
        mock_chat.return_value = {"answer": "ok", "conversation_id": "upstream-book-id-001"}

        resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": "v46_blocking_book_id_inputs",
                "intent": "init world model",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        inputs = mock_chat.call_args.kwargs["inputs"]
        self.assertEqual(inputs["book_id"], body["book_id"])
        self.assertEqual(inputs["book_name"], "v46_blocking_book_id_inputs")
        self.assertEqual(inputs["active_file"], "world_model.md")

    def test_deduce_missing_required_field_returns_400(self):
        resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": "v46_missing",
                "intent": "test",
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "MISSING_FIELD")

    def test_deduce_without_api_key_or_mock_returns_502(self):
        no_key_storage = self.temp_dir / "no_key_storage"
        no_key_dev_repo = self.temp_dir / "no_key_dev_repo"
        with patch.dict(
            os.environ,
            {
                "DIFY_API_KEY": "",
                "DIFY_WORLD_MODEL_API_KEY": "",
                "DIFY_WORLD_CORE_API_KEY": "",
            },
        ):
            no_key_app = gs.create_app(
                storage_root=str(no_key_storage),
                dev_repo_root=str(no_key_dev_repo),
            )
            no_key_app.testing = True
            client = no_key_app.test_client()
            resp = client.post(
                "/api/world/deduce",
                json={
                    "book_name": "v46_no_key",
                    "intent": "test",
                    "active_file": "world_model.md",
                },
            )
        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertEqual(body["code"], "DIFY_API_FAILED")

    @patch("agents.world_draft.stop_chat_message")
    def test_stop_generation_proxies_native_chat_stop(self, mock_stop):
        mock_stop.return_value = {"result": "success"}

        resp = self.client.post(
            "/api/world/stop_generation",
            json={
                "book_name": "v46_stop_generation",
                "active_file": "brainstorm.md",
                "task_id": "task-stop-001",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["task_id"], "task-stop-001")
        self.assertEqual(body["result"], "success")
        mock_stop.assert_called_once()
        kwargs = mock_stop.call_args.kwargs
        self.assertEqual(kwargs["task_id"], "task-stop-001")
        self.assertEqual(kwargs["user"], "loregit-ui")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_delta_carries_task_id(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "正文内容",
                        "conversation_id": "conv-task-1",
                        "task_id": "task-123",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_task_id",
                "intent": "task id passthrough",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        delta_event = next(event for event in events if event["event"] == "delta")
        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(delta_event["data"].get("task_id"), "task-123")
        self.assertEqual(done_event["data"].get("task_id"), "task-123")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_detached_job_does_not_persist_or_reuse_conversation(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "detached job done",
                        "conversation_id": "upstream-detached-001",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_detached_job",
                "intent": "button job should not enter chat history",
                "active_file": "chapter_draft.md",
                "file_type": "chapter",
                "route_agent_key": "continuation_agent",
                "thread_id": "local-detached-001",
                "conversation_id": "upstream-should-not-reuse",
                "detached_job": True,
            },
        )

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(done_event["data"].get("conversation_id"), "local-detached-001")
        self.assertEqual(done_event["data"].get("upstream_conversation_id"), "upstream-detached-001")
        self.assertIsNone(mock_stream.call_args.kwargs.get("conversation_id"))
        self.assertEqual(list(self.dev_repo_dir.rglob("*local-detached-001*.jsonl")), [])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_retries_transient_invalid_json_workflow_failure_before_side_effects(self, mock_stream):
        transient_failure = {
            "event": "workflow_finished",
            "data": {
                "event": "workflow_finished",
                "status": "failed",
                "error": "got invalid json object. error: Expecting value: line 1 column 1 (char 0)",
            },
        }
        mock_stream.side_effect = [
            iter([transient_failure]),
            iter(
                [
                    {
                        "event": "message",
                        "data": {
                            "event": "message",
                            "answer": "retry recovered answer",
                            "conversation_id": "conv-retry-ok",
                        },
                    }
                ]
            ),
        ]

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_transient_retry",
                "intent": "retry transient invalid json",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        self.assertEqual(mock_stream.call_count, 2)
        event_names = [event["event"] for event in events]
        self.assertNotIn("error", event_names)
        retry_stage = next(
            event for event in events
            if event["event"] == "stage" and event["data"].get("stage_code") == "dify_retry"
        )
        self.assertIn("自动重试", retry_stage["data"].get("stage_text", ""))
        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("retry recovered answer", delta_text)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_does_not_retry_workflow_failure_after_visible_delta(self, mock_stream):
        transient_failure = {
            "event": "workflow_finished",
            "data": {
                "event": "workflow_finished",
                "status": "failed",
                "error": "got invalid json object. error: Expecting value: line 1 column 1 (char 0)",
            },
        }
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "partial visible answer",
                        "conversation_id": "conv-retry-no",
                    },
                },
                transient_failure,
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_no_retry_after_delta",
                "intent": "do not retry after visible output",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        self.assertEqual(mock_stream.call_count, 1)
        error_event = next(event for event in events if event["event"] == "error")
        self.assertEqual(error_event["data"].get("code"), "DIFY_WORKFLOW_FAILED")
        self.assertNotIn(
            "dify_retry",
            [event["data"].get("stage_code") for event in events if event["event"] == "stage"],
        )

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_prefixes_world_model_template_bootstrap_query(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "世界模型初版已生成",
                        "conversation_id": "conv-world-bootstrap-1",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_world_bootstrap_query",
                "intent": "请基于已有章节建立主轴",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self._parse_sse_events(resp.get_data(as_text=True))

        query = mock_stream.call_args.kwargs["query"]
        self.assertIn("世界模型初始化任务", query)
        self.assertIn("读者承诺与主轴", query)
        self.assertIn("冲突发动机", query)
        self.assertIn("下游工作流接口", query)
        self.assertTrue(query.rstrip().endswith("请基于已有章节建立主轴"))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_does_not_prefix_non_world_bootstrap_query(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "大纲讨论完成",
                        "conversation_id": "conv-outline-no-bootstrap-1",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_outline_no_bootstrap_query",
                "intent": "讨论第二卷冲突",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self._parse_sse_events(resp.get_data(as_text=True))

        query = mock_stream.call_args.kwargs["query"]
        self.assertEqual(query, "讨论第二卷冲突")
        self.assertNotIn("世界模型初始化任务", query)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_restores_upstream_conversation_from_local_thread(self, mock_stream):
        mock_stream.side_effect = [
            iter(
                [
                    {
                        "event": "message",
                        "data": {
                            "event": "message",
                            "answer": "first answer",
                            "conversation_id": "upstream-001",
                        },
                    }
                ]
            ),
            iter(
                [
                    {
                        "event": "message",
                        "data": {
                            "event": "message",
                            "answer": "second answer",
                            "conversation_id": "upstream-001",
                        },
                    }
                ]
            ),
        ]

        first_resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_upstream_memory",
                "intent": "first turn",
                "active_file": "world_model.md",
                "thread_id": "conv-local-001",
            },
        )
        self.assertEqual(first_resp.status_code, 200)
        self._parse_sse_events(first_resp.get_data(as_text=True))

        second_resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_upstream_memory",
                "intent": "second turn",
                "active_file": "world_model.md",
                "thread_id": "conv-local-001",
            },
        )
        self.assertEqual(second_resp.status_code, 200)
        events = self._parse_sse_events(second_resp.get_data(as_text=True))

        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(done_event["data"].get("conversation_id"), "conv-local-001")
        self.assertEqual(done_event["data"].get("upstream_conversation_id"), "upstream-001")
        self.assertEqual(mock_stream.call_args.kwargs["conversation_id"], "upstream-001")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_maps_nested_message_events_to_stage(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "workflow_started", "conversation_id": "conv-stage-1"},
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "链路已通", "conversation_id": "conv-stage-1"},
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_stage",
                "intent": "stream stage test",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        event_names = [event["event"] for event in events]
        self.assertIn("ack", event_names)
        self.assertIn("stage", event_names)
        self.assertIn("delta", event_names)
        self.assertIn("done", event_names)
        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("active_file"), "world_model.md")
        self.assertEqual(ack_event["data"].get("write_scope"), "active_file_strict")

        stage_event = next(event for event in events if event["event"] == "stage")
        self.assertEqual(stage_event["data"].get("stage_code"), "workflow_started")
        self.assertEqual(stage_event["data"].get("source_event"), "workflow_started")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_sanitizes_stage_node_labels(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "node_started",
                        "node_title": "问题分类器_2started",
                        "node_type": "agent",
                        "conversation_id": "conv-stage-sanitize-1",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "node_finished",
                        "node_title": "COMMIT_AGENT",
                        "node_type": "agent",
                        "conversation_id": "conv-stage-sanitize-1",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "链路已通",
                        "conversation_id": "conv-stage-sanitize-1",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stage_label_sanitize",
                "intent": "sanitize labels",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        stage_events = [event for event in events if event["event"] == "stage"]
        self.assertGreaterEqual(len(stage_events), 2)
        self.assertEqual(stage_events[0]["data"].get("node_title"), "问题分类器")
        self.assertIn("问题分类器", stage_events[0]["data"].get("stage_text", ""))
        self.assertEqual(stage_events[1]["data"].get("node_title"), "草稿写入")
        self.assertIn("草稿写入", stage_events[1]["data"].get("stage_text", ""))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_persists_inline_resend_as_tail_rewrite(self, mock_stream):
        mock_stream.side_effect = [
            iter(
                [
                    {
                        "event": "message",
                        "data": {"event": "message", "answer": "旧回答", "conversation_id": "conv-stream-rewrite-1"},
                    }
                ]
            ),
            iter(
                [
                    {
                        "event": "message",
                        "data": {"event": "message", "answer": "新回答", "conversation_id": "conv-stream-rewrite-1"},
                    }
                ]
            ),
        ]

        first_resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_tail_rewrite",
                "intent": "旧问题",
                "active_file": "arc_outline.md",
                "file_type": "outline",
                "thread_id": "conv-stream-rewrite-1",
            },
        )
        self.assertEqual(first_resp.status_code, 200)
        self._parse_sse_events(first_resp.get_data(as_text=True))

        context_resp = self.client.get(
            "/api/conversations/context",
            query_string={
                "book_name": "v46_stream_tail_rewrite",
                "agent": "outline_agent",
            },
        )
        self.assertEqual(context_resp.status_code, 200)
        initial_messages = context_resp.get_json()["messages"]
        self.assertEqual(len(initial_messages), 2)
        rewrite_user_message_id = initial_messages[0]["id"]

        rewrite_resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_tail_rewrite",
                "intent": "新问题",
                "active_file": "arc_outline.md",
                "file_type": "outline",
                "thread_id": "conv-stream-rewrite-1",
                "rewrite_user_message_id": rewrite_user_message_id,
            },
        )
        self.assertEqual(rewrite_resp.status_code, 200)
        self._parse_sse_events(rewrite_resp.get_data(as_text=True))

        final_context_resp = self.client.get(
            "/api/conversations/context",
            query_string={
                "book_name": "v46_stream_tail_rewrite",
                "agent": "outline_agent",
            },
        )
        self.assertEqual(final_context_resp.status_code, 200)
        body = final_context_resp.get_json()
        self.assertEqual(body["conversation_id"], "conv-stream-rewrite-1")
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][0]["text"], "新问题")
        self.assertEqual(body["messages"][1]["text"], "新回答")

    @patch("agents.world_draft._draft_file_snapshots")
    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_detects_cross_file_markdown_write_for_review(self, mock_stream, mock_snapshots):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "workflow_finished",
                        "conversation_id": "conv-cross-file-review-1",
                        "data": {"outputs": {"answer": "已整理篇章二章节大纲。", "sync_status": "success", "sync_commit_id": "abc999def"}},
                    },
                }
            ]
        )
        mock_snapshots.side_effect = [
            {
                "arc_outline.md": {"exists": True, "commit_id": "base-1", "content": "旧 arc", "etag": "etag-arc-1"},
                "chapter_outline.md": {"exists": True, "commit_id": "base-1", "content": "旧 chapter", "etag": "etag-chapter-1"},
                "brainstorm.md": {"exists": False, "commit_id": None, "content": "", "etag": "empty"},
                "master_outline.md": {"exists": False, "commit_id": None, "content": "", "etag": "empty"},
            },
            {
                "arc_outline.md": {"exists": True, "commit_id": "base-1", "content": "旧 arc", "etag": "etag-arc-1"},
                "chapter_outline.md": {"exists": True, "commit_id": "commit-2", "content": "新 chapter", "etag": "etag-chapter-2"},
                "brainstorm.md": {"exists": False, "commit_id": None, "content": "", "etag": "empty"},
                "master_outline.md": {"exists": False, "commit_id": None, "content": "", "etag": "empty"},
            },
        ]

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_cross_file_review",
                "intent": "把篇章二下沉到 chapter_outline.md",
                "active_file": "arc_outline.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        draft_ready_event = next(event for event in events if event["event"] == "draft_ready")
        self.assertEqual(draft_ready_event["data"].get("file_name"), "chapter_outline.md")
        self.assertTrue(draft_ready_event["data"].get("draft_changed"))
        self.assertIn("chapter_outline.md", draft_ready_event["data"].get("changed_files", []))

        done_event = next(event for event in events if event["event"] == "done")
        self.assertTrue(done_event["data"].get("draft_changed"))
        self.assertEqual(done_event["data"].get("review_target_file"), "chapter_outline.md")
        self.assertIn("chapter_outline.md", done_event["data"].get("changed_files", []))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_init_intent_infers_world_core_scope_in_ack(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "初始化完成", "conversation_id": "conv-init-1"},
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_init_scope",
                "intent": "初始化本书双底座并完成双写",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("write_scope"), "world_core")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_init_intent_overrides_strict_scope_in_ack(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "初始化完成", "conversation_id": "conv-init-2"},
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_init_scope_strict",
                "intent": "初始化本书双底座并完成双写",
                "active_file": "world_model.md",
                "write_scope": "active_file_strict",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("write_scope"), "world_core")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_fallback_reads_workflow_finished_outputs_answer(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "workflow_started", "conversation_id": "conv-fallback-1"},
                },
                {
                    "event": "message",
                    "data": {
                        "event": "workflow_finished",
                        "conversation_id": "conv-fallback-1",
                        "data": {"outputs": {"answer": "仅在 workflow_finished 提供文本"}},
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_fallback",
                "intent": "stream fallback test",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        deltas = [event for event in events if event["event"] == "delta"]
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["data"].get("text"), "仅在 workflow_finished 提供文本")

        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(done_event["data"].get("answer"), "仅在 workflow_finished 提供文本")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_empty_answer_without_draft_emits_error(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "workflow_started", "conversation_id": "conv-empty-upstream"},
                },
                {
                    "event": "message",
                    "data": {
                        "event": "workflow_finished",
                        "conversation_id": "conv-empty-upstream",
                        "data": {"outputs": {"answer": "\n\n"}},
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_empty_answer",
                "intent": "empty answer test",
                "active_file": "world_model.md",
                "conversation_id": "conv-empty-answer",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        self.assertFalse(any(event["event"] == "done" for event in events))
        errors = [event for event in events if event["event"] == "error"]
        self.assertEqual(errors[-1]["data"].get("code"), "DIFY_EMPTY_ANSWER")
        self.assertEqual(list(self.dev_repo_dir.rglob("*conv-empty-answer*.jsonl")), [])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_emits_reasoning_event_from_agent_thought(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "agent_thought",
                    "data": {
                        "thought": "先确认故事当前所处阶段，再决定讨论高度。",
                        "conversation_id": "conv-reasoning-1",
                    },
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "继续讨论", "conversation_id": "conv-reasoning-1"},
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_reasoning",
                "intent": "reasoning test",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning_event = next(event for event in events if event["event"] == "reasoning")
        self.assertEqual(reasoning_event["data"].get("label"), "已深度思考")
        self.assertIn("当前所处阶段", reasoning_event["data"].get("text", ""))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_compacts_english_agent_scratchpad(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "agent_thought",
                    "data": {
                        "thought": (
                            "Let me start by reading chapter_draft.md, chapter_outline.md, "
                            "summary.md, status_card.md, world_model.md, style_guide.md, "
                            "and error_archive.md. Now I need to go through the review dimensions "
                            "one by one before producing the final answer."
                        ),
                        "conversation_id": "conv-reasoning-compact",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "review passed",
                        "conversation_id": "conv-reasoning-compact",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_reasoning_compact",
                "intent": "reasoning compact test",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning_event = next(event for event in events if event["event"] == "reasoning")
        reasoning_text = reasoning_event["data"].get("text", "")
        self.assertNotIn("Let me", reasoning_text)
        self.assertNotIn("Now I", reasoning_text)
        self.assertIn("正在读取", reasoning_text)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_routes_visible_english_scratchpad_to_reasoning(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": (
                            "Let me now read the detailed content of chapter_draft.md, "
                            "chapter_outline.md, error_archive.md and other key files "
                            "to conduct a thorough review."
                        ),
                        "conversation_id": "conv-visible-scratchpad",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "审核通过：没有发现新问题。",
                        "conversation_id": "conv-visible-scratchpad",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_visible_scratchpad",
                "intent": "visible scratchpad test",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "reasoning")
        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("正在读取", reasoning_text)
        self.assertNotIn("Let me", delta_text)
        self.assertIn("审核通过", delta_text)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_buffers_chunked_visible_scratchpad(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "Let me start by reading ",
                        "conversation_id": "conv-chunked-scratchpad",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "chapter_draft.md and error_archive.md before the review.",
                        "conversation_id": "conv-chunked-scratchpad",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "审核通过：没有发现新问题。",
                        "conversation_id": "conv-chunked-scratchpad",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_chunked_scratchpad",
                "intent": "chunked scratchpad test",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "reasoning")
        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("正在读取", reasoning_text)
        self.assertNotIn("Let me", delta_text)
        self.assertNotIn("chapter_draft.md", delta_text)
        self.assertIn("审核通过", delta_text)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_buffers_chunked_reasoning_scratchpad(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {"event": "agent_thought", "data": {"thought": "\nLet", "conversation_id": "conv-chunked-reasoning"}},
                {"event": "agent_thought", "data": {"thought": " me", "conversation_id": "conv-chunked-reasoning"}},
                {"event": "agent_thought", "data": {"thought": " start by reading chapter_draft.md", "conversation_id": "conv-chunked-reasoning"}},
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "审核通过：没有发现新问题。",
                        "conversation_id": "conv-chunked-reasoning",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_chunked_reasoning",
                "intent": "chunked reasoning test",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "reasoning")
        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("正在读取", reasoning_text)
        self.assertNotIn("Let me", reasoning_text)
        self.assertIn("审核通过", delta_text)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_emits_safe_preview_before_first_delta(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "node_finished",
                        "node_title": "结构收束",
                        "node_type": "llm",
                        "outputs": {
                            "text": "先给用户一个中间可读总结，再等待最终正文首字。"
                        },
                        "conversation_id": "conv-preview-1",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "最终正文",
                        "conversation_id": "conv-preview-1",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_preview",
                "intent": "preview test",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        preview_event = next(event for event in events if event["event"] == "preview")
        delta_event = next(event for event in events if event["event"] == "delta")
        preview_index = events.index(preview_event)
        delta_index = events.index(delta_event)
        self.assertLess(preview_index, delta_index)
        self.assertEqual(preview_event["data"].get("label"), "结构收束")
        self.assertIn("中间可读总结", preview_event["data"].get("text", ""))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_done_accepts_workflow_sync_status_confirmation(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "workflow_finished",
                        "conversation_id": "conv-sync-meta-1",
                        "data": {
                            "outputs": {
                                "answer": "执行完成",
                                "sync_status": "success",
                                "sync_commit_id": "abc123def",
                                "sync_message": "sync_all success",
                            }
                        },
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_sync_meta",
                "intent": "sync status meta test",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(done_event["data"].get("sync_status"), "success")
        self.assertEqual(done_event["data"].get("sync_commit_id"), "abc123def")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_splits_single_think_block_from_visible_delta(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "<think>先判断层级</think>这是正文", "conversation_id": "conv-think-1"},
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_think_single",
                "intent": "single think",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        deltas = [event["data"].get("text", "") for event in events if event["event"] == "delta"]
        reasoning = [event["data"].get("text", "") for event in events if event["event"] == "reasoning"]
        self.assertEqual("".join(deltas), "这是正文")
        self.assertEqual("".join(reasoning), "先判断层级")
        self.assertEqual(len(reasoning), 1)

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_splits_multiple_think_blocks(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "<think>第一段</think>正文A<think>第二段</think>正文B", "conversation_id": "conv-think-2"},
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_think_multi",
                "intent": "multi think",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        deltas = [event["data"].get("text", "") for event in events if event["event"] == "delta"]
        reasoning = [event["data"].get("text", "") for event in events if event["event"] == "reasoning"]
        self.assertEqual("".join(deltas), "正文A正文B")
        self.assertEqual(reasoning, ["第一段", "第二段"])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_think_block_and_reasoning_event_coexist(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "agent_thought",
                    "data": {
                        "thought": "已有 reasoning event",
                        "conversation_id": "conv-think-3",
                    },
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "<think>think标签内容</think>最终正文", "conversation_id": "conv-think-3"},
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_think_mix",
                "intent": "mixed think",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        reasoning = [event["data"].get("text", "") for event in events if event["event"] == "reasoning"]
        deltas = [event["data"].get("text", "") for event in events if event["event"] == "delta"]
        self.assertIn("已有 reasoning event", reasoning)
        self.assertIn("think标签内容", reasoning)
        self.assertEqual("".join(deltas), "最终正文")
        done_event = next(event for event in events if event["event"] == "done")
        self.assertEqual(done_event["data"].get("answer"), "最终正文")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_think_block_cross_chunk_streams_before_close(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "<thi", "conversation_id": "conv-think-4"},
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "nk>跨chunk思考", "conversation_id": "conv-think-4"},
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "</think>正文", "conversation_id": "conv-think-4"},
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_think_chunked",
                "intent": "chunked think",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        reasoning = [event["data"].get("text", "") for event in events if event["event"] == "reasoning"]
        reasoning_statuses = [event["data"].get("status", "") for event in events if event["event"] == "reasoning"]
        deltas = [event["data"].get("text", "") for event in events if event["event"] == "delta"]
        self.assertEqual(reasoning, ["跨chunk思考", "跨chunk思考"])
        self.assertEqual(reasoning_statuses, ["streaming", "done"])
        self.assertEqual("".join(deltas), "正文")

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_think_block_streams_incrementally_within_same_block(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "<think>第一句", "conversation_id": "conv-think-5"},
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "第二句", "conversation_id": "conv-think-5"},
                },
                {
                    "event": "message",
                    "data": {"event": "message", "answer": "</think>正文", "conversation_id": "conv-think-5"},
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_think_incremental",
                "intent": "incremental think",
                "active_file": "brainstorm.md",
                "file_type": "outline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        reasoning_events = [event["data"] for event in events if event["event"] == "reasoning"]
        self.assertEqual(
            [(item.get("text"), item.get("status")) for item in reasoning_events],
            [
                ("第一句", "streaming"),
                ("第二句", "streaming"),
                ("第一句第二句", "done"),
            ],
        )
        self.assertEqual(
            [item.get("append") for item in reasoning_events],
            [True, True, None],
        )

    def test_deduce_stream_rejects_non_world_active_file(self):
        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_invalid_target",
                "intent": "stream invalid target test",
                "active_file": "notes/private.md",
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "TARGET_PATH_FORBIDDEN")
        self.assertIn("active_file must be readable", body["message"])

    def test_deduce_stream_allows_summary_active_file(self):
        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_summary_target",
                "intent": "只读取 summary 并回复一句确认",
                "active_file": "summary.md",
                "file_type": "summary",
                "mock_ai_markdown": "summary 通道已命中",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        ack_event = next(event for event in events if event["event"] == "ack")
        self.assertEqual(ack_event["data"].get("file_name"), "summary.md")
        self.assertEqual(ack_event["data"].get("file_type"), "summary")

    def test_deduce_stream_rejects_file_type_mismatch(self):
        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_stream_mismatch",
                "intent": "类型错配测试",
                "active_file": "summary.md",
                "file_type": "world_core",
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("does not match active_file", body["message"])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_hidden_payload_masked_and_validated(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "先输出分析过程。\n[JSON_PAYLOAD_START]{\"writes\": [{\"file_name\": \"world_model.md\", \"op\": \"update\", \"content\": \"# 隐藏写入内容\"}]}",
                        "conversation_id": "conv-hidden-1",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_hidden_payload_sync",
                "intent": "暗门截流回归",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("先输出分析过程。", delta_text)
        self.assertNotIn("[JSON_PAYLOAD_START]", delta_text)
        self.assertNotIn("git_sync_success", [event["event"] for event in events])

        done_event = next(event for event in events if event["event"] == "done")
        self.assertNotIn("[JSON_PAYLOAD_START]", done_event["data"].get("answer", ""))
        self.assertTrue(done_event["data"].get("hidden_payload_detected"))
        self.assertTrue(done_event["data"].get("hidden_payload_valid"))
        self.assertFalse(done_event["data"].get("write_confirmed"))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_hidden_marker_cross_chunk_no_leak(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "跨块测试开始[JSON_",
                        "conversation_id": "conv-hidden-2",
                    },
                },
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "PAYLOAD_START]{\"writes\": [{\"file_name\": \"world_model.md\", \"op\": \"update\", \"content\": \"跨块写入\"}]}",
                        "conversation_id": "conv-hidden-2",
                    },
                },
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_hidden_payload_cross_chunk",
                "intent": "跨 chunk 命中 marker",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        delta_text = "".join(event["data"].get("text", "") for event in events if event["event"] == "delta")
        self.assertIn("跨块测试开始", delta_text)
        self.assertNotIn("[JSON_", delta_text)
        self.assertNotIn("PAYLOAD_START]", delta_text)
        self.assertNotIn("git_sync_success", [event["event"] for event in events])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_marker_without_json_payload_hard_error(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "只给分析，不给文件[JSON_PAYLOAD_START]   ",
                        "conversation_id": "conv-hidden-3",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_hidden_payload_missing_file",
                "intent": "marker 无 file",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        error_events = [e for e in events if e["event"] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["data"].get("code"), "JSON_PAYLOAD_INVALID")
        self.assertIn("隐藏 JSON 载荷格式错误", error_events[0]["data"].get("message", ""))
        self.assertNotIn("done", [event["event"] for event in events])

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_extra_data_payload_reports_readable_error(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": '[JSON_PAYLOAD_START]{"writes":[{"file_name":"world_model.md","content":"A"}]}\n{"extra":true}',
                        "conversation_id": "conv-hidden-extra-1",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_hidden_payload_extra_data",
                "intent": "marker extra data",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))

        error_events = [e for e in events if e["event"] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["data"].get("code"), "JSON_PAYLOAD_INVALID")
        self.assertIn("隐藏 JSON 载荷格式错误", error_events[0]["data"].get("message", ""))
        self.assertIn("marker 之后混入了额外文本", error_events[0]["data"].get("message", ""))

    @patch("agents.world_draft.chat_messages_stream")
    def test_deduce_stream_without_marker_keeps_legacy_path(self, mock_stream):
        mock_stream.return_value = iter(
            [
                {
                    "event": "message",
                    "data": {
                        "event": "message",
                        "answer": "普通回答，不触发暗门。",
                        "conversation_id": "conv-hidden-4",
                    },
                }
            ]
        )

        resp = self.client.post(
            "/api/world/deduce_stream",
            json={
                "book_name": "v46_hidden_payload_legacy",
                "intent": "保持兼容",
                "active_file": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        event_names = [event["event"] for event in events]
        self.assertIn("done", event_names)
        self.assertNotIn("git_sync_success", event_names)

    def test_get_file_rejects_conflicting_book_id_and_book_name(self):
        resp = self.client.get(
            "/books/get_file",
            query_string={
                "book_id": "donk_3ac38360",
                "book_name": "not_the_same_book",
                "file_name": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["code"], "BOOK_LOCATOR_CONFLICT")

    def test_sync_all_rejects_read_only_active_file_for_write(self):
        init_resp = self.client.post(
            "/books/init",
            json={
                "book_name": "v46_sync_readonly",
            },
        )
        self.assertEqual(init_resp.status_code, 200)

        read_resp = self.client.get(
            "/books/get_file",
            query_string={
                "book_name": "v46_sync_readonly",
                "file_name": "world_model.md",
            },
        )
        self.assertEqual(read_resp.status_code, 200)
        etag = read_resp.get_json()["etag"]

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": "v46_sync_readonly",
                "write_scope": "active_file_strict",
                "active_file": "summary.md",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "x",
                        "base_etag": etag,
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "TARGET_PATH_FORBIDDEN")
        self.assertIn("read-only", body["message"])


if __name__ == "__main__":
    unittest.main()
