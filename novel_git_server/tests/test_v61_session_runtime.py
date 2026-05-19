import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V61SessionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v61_session_runtime_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.dev_repo_dir = self.temp_dir / "dev_repo"
        self.app = gs.create_app(
            storage_root=str(self.temp_dir / "storage"),
            dev_repo_root=str(self.dev_repo_dir),
        )
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_deduce_persists_outline_agent_conversation_runtime(self):
        resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": "v61_outline_conv",
                "intent": "把头脑风暴整理成主线",
                "active_file": "brainstorm.md",
                "file_type": "outline",
                "mock_ai_markdown": "outline answer",
                "conversation_id": "conv-outline-1",
            },
        )
        self.assertEqual(resp.status_code, 200)

        agent_dir = self.dev_repo_dir / "conversations" / "outline_agent"
        self.assertTrue(agent_dir.exists())

        index_files = list(agent_dir.glob("*.index.json"))
        self.assertEqual(len(index_files), 1)
        index_payload = json.loads(index_files[0].read_text(encoding="utf-8"))
        self.assertEqual(index_payload["active_conversation_id"], "conv-outline-1")
        self.assertEqual(index_payload["conversations"][0]["last_active_file"], "brainstorm.md")
        self.assertEqual(index_payload["conversations"][0]["upstream_conversation_id"], "conv-outline-1")

        conv_files = list(agent_dir.glob("*conv-outline-1*.jsonl"))
        self.assertEqual(len(conv_files), 1)
        raw_lines = conv_files[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw_lines), 2)
        user_row = json.loads(raw_lines[0])
        assistant_row = json.loads(raw_lines[1])
        self.assertEqual(user_row["role"], "user")
        self.assertEqual(user_row["active_file"], "brainstorm.md")
        self.assertEqual(user_row["upstream_conversation_id"], "conv-outline-1")
        self.assertEqual(assistant_row["role"], "assistant")
        self.assertEqual(assistant_row["text"], "outline answer")
        self.assertEqual(assistant_row["upstream_conversation_id"], "conv-outline-1")

    def test_conversation_context_returns_active_agent_messages(self):
        self.client.post(
            "/api/world/deduce",
            json={
                "book_name": "v61_context",
                "intent": "整理大纲",
                "active_file": "master_outline.md",
                "file_type": "outline",
                "mock_ai_markdown": "master answer",
                "conversation_id": "conv-outline-2",
            },
        )

        resp = self.client.get(
            "/api/conversations/context",
            query_string={
                "book_name": "v61_context",
                "agent": "outline_agent",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["agent_key"], "outline_agent")
        self.assertEqual(body["active_conversation_id"], "conv-outline-2")
        self.assertEqual(body["conversation_id"], "conv-outline-2")
        self.assertEqual(body["upstream_conversation_id"], "conv-outline-2")
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][0]["active_file"], "master_outline.md")
        self.assertEqual(body["messages"][1]["text"], "master answer")
        self.assertEqual(body["messages"][0]["upstream_conversation_id"], "conv-outline-2")

    def test_tail_rewrite_replaces_last_turn_instead_of_appending_duplicate(self):
        book_name = "v61_tail_rewrite"
        conversation_id = "conv-outline-tail-rewrite"

        first_resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": book_name,
                "intent": "旧问题",
                "active_file": "arc_outline.md",
                "file_type": "outline",
                "mock_ai_markdown": "旧回答",
                "conversation_id": conversation_id,
            },
        )
        self.assertEqual(first_resp.status_code, 200)

        context_resp = self.client.get(
            "/api/conversations/context",
            query_string={
                "book_name": book_name,
                "agent": "outline_agent",
            },
        )
        self.assertEqual(context_resp.status_code, 200)
        initial_messages = context_resp.get_json()["messages"]
        self.assertEqual(len(initial_messages), 2)
        rewrite_user_message_id = initial_messages[0]["id"]

        rewrite_resp = self.client.post(
            "/api/world/deduce",
            json={
                "book_name": book_name,
                "intent": "新问题",
                "active_file": "arc_outline.md",
                "file_type": "outline",
                "mock_ai_markdown": "新回答",
                "conversation_id": conversation_id,
                "rewrite_user_message_id": rewrite_user_message_id,
            },
        )
        self.assertEqual(rewrite_resp.status_code, 200)

        final_context_resp = self.client.get(
            "/api/conversations/context",
            query_string={
                "book_name": book_name,
                "agent": "outline_agent",
            },
        )
        self.assertEqual(final_context_resp.status_code, 200)
        body = final_context_resp.get_json()
        self.assertEqual(body["conversation_id"], conversation_id)
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertEqual(body["messages"][0]["text"], "新问题")
        self.assertEqual(body["messages"][1]["role"], "assistant")
        self.assertEqual(body["messages"][1]["text"], "新回答")

        agent_dir = self.dev_repo_dir / "conversations" / "outline_agent"
        conv_files = list(agent_dir.glob(f"*{conversation_id}*.jsonl"))
        self.assertEqual(len(conv_files), 1)
        raw_lines = conv_files[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw_lines), 2)

    def test_session_management_routes_create_rename_activate_archive(self):
        init_book = "v61_manage"

        create_resp = self.client.post(
            "/api/conversations/create",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "active_file": "brainstorm.md",
                "title": "初始灵感会话",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        body = create_resp.get_json()
        conv_id = body["active_conversation_id"]
        self.assertTrue(conv_id)
        self.assertEqual(body["conversations"][0]["title"], "初始灵感会话")

        rename_resp = self.client.post(
            "/api/conversations/rename",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "conversation_id": conv_id,
                "title": "重命名后的会话",
            },
        )
        self.assertEqual(rename_resp.status_code, 200)
        renamed = rename_resp.get_json()
        self.assertEqual(renamed["conversations"][0]["title"], "重命名后的会话")

        create_resp_2 = self.client.post(
            "/api/conversations/create",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "active_file": "master_outline.md",
                "title": "第二会话",
            },
        )
        self.assertEqual(create_resp_2.status_code, 200)
        second_id = create_resp_2.get_json()["active_conversation_id"]
        self.assertNotEqual(conv_id, second_id)

        activate_resp = self.client.post(
            "/api/conversations/activate",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "conversation_id": conv_id,
            },
        )
        self.assertEqual(activate_resp.status_code, 200)
        activated = activate_resp.get_json()
        self.assertEqual(activated["active_conversation_id"], conv_id)
        self.assertEqual(activated["conversation_id"], conv_id)

        archive_resp = self.client.post(
            "/api/conversations/archive",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "conversation_id": conv_id,
            },
        )
        self.assertEqual(archive_resp.status_code, 200)
        archived = archive_resp.get_json()
        self.assertEqual(archived["active_conversation_id"], second_id)
        self.assertTrue(all(item["conversation_id"] != conv_id for item in archived["conversations"]))

    def test_delete_conversation_removes_index_and_message_file(self):
        init_book = "v61_delete"

        create_resp = self.client.post(
            "/api/conversations/create",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "active_file": "brainstorm.md",
                "title": "待删除会话",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        first_id = create_resp.get_json()["active_conversation_id"]

        self.client.post(
            "/api/world/deduce",
            json={
                "book_name": init_book,
                "intent": "补一轮消息",
                "active_file": "brainstorm.md",
                "file_type": "outline",
                "mock_ai_markdown": "delete me",
                "conversation_id": first_id,
            },
        )

        create_resp_2 = self.client.post(
            "/api/conversations/create",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "active_file": "master_outline.md",
                "title": "保留会话",
            },
        )
        self.assertEqual(create_resp_2.status_code, 200)
        second_id = create_resp_2.get_json()["active_conversation_id"]

        agent_dir = self.dev_repo_dir / "conversations" / "outline_agent"
        deleted_files = list(agent_dir.glob(f"*{first_id}*.jsonl"))
        self.assertEqual(len(deleted_files), 1)

        delete_resp = self.client.post(
            "/api/conversations/delete",
            json={
                "book_name": init_book,
                "agent": "outline_agent",
                "conversation_id": first_id,
            },
        )
        self.assertEqual(delete_resp.status_code, 200)
        body = delete_resp.get_json()
        self.assertEqual(body["active_conversation_id"], second_id)
        self.assertTrue(all(item["conversation_id"] != first_id for item in body["conversations"]))
        self.assertEqual(body["conversation_id"], second_id)
        self.assertFalse(deleted_files[0].exists())

        index_files = list(agent_dir.glob("*.index.json"))
        self.assertEqual(len(index_files), 1)
        index_payload = json.loads(index_files[0].read_text(encoding="utf-8"))
        self.assertEqual(index_payload["active_conversation_id"], second_id)
        self.assertTrue(all(item["conversation_id"] != first_id for item in index_payload["conversations"]))


if __name__ == "__main__":
    unittest.main()
