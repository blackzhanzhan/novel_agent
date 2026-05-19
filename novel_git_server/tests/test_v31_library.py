import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.book_storage import generate_deterministic_id  # noqa: E402
from utils.session_runtime import ALLOWED_AGENT_KEYS, resolve_dev_repo_root  # noqa: E402


class V31LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_library_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _commit_count(self, book_id: str) -> int:
        repo_dir = self.temp_dir / book_id
        if not (repo_dir / ".git").exists():
            return 0
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return int(result.stdout.strip())

    def _write_conversation_runtime(self, book_id: str, conversation_id: str = "conv_abc") -> list[Path]:
        conv_root = resolve_dev_repo_root(None) / "conversations"
        created_files: list[Path] = []
        for agent in ALLOWED_AGENT_KEYS:
            agent_dir = conv_root / agent
            agent_dir.mkdir(parents=True, exist_ok=True)
            idx = agent_dir / f"{book_id}.index.json"
            idx.write_text(
                json.dumps(
                    {
                        "book_id": book_id,
                        "agent_key": agent,
                        "active_conversation_id": conversation_id,
                        "conversations": [{"conversation_id": conversation_id}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            created_files.append(idx)
            msgs = agent_dir / f"{book_id}__{conversation_id}.jsonl"
            msgs.write_text('{"role":"user","text":"hi"}\n', encoding="utf-8")
            created_files.append(msgs)

        for path in created_files:
            self.addCleanup(lambda p=path: p.unlink(missing_ok=True))
        return created_files

    def test_books_init_writes_metadata_and_git_commit(self):
        resp = self.client.post(
            "/books/init",
            json={"book_id": "cyber_01", "book_name": "cyber story"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")

        metadata_path = Path(body["metadata_path"])
        self.assertTrue(metadata_path.exists())

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["book_id"], "cyber_01")
        self.assertEqual(metadata["book_name"], "cyber story")

        repo_dir = self.temp_dir / "cyber_01"
        self.assertTrue((repo_dir / "brainstorm.md").exists())
        self.assertTrue((repo_dir / "master_outline.md").exists())
        self.assertTrue((repo_dir / "arc_outline.md").exists())
        self.assertTrue((repo_dir / "chapter_outline.md").exists())
        world_model = (repo_dir / "world_model.md").read_text(encoding="utf-8")
        status_card = (repo_dir / "status_card.md").read_text(encoding="utf-8")
        domain_rules = (repo_dir / "domain_rules.md").read_text(encoding="utf-8")
        self.assertIn("创作约束引擎", world_model)
        self.assertIn("读者承诺与主轴", world_model)
        self.assertIn("下游工作流接口", world_model)
        self.assertIn("下一章约束", status_card)
        self.assertIn("domain-rule 示例", domain_rules)
        subjects = subprocess.run(
            ["git", "log", "--pretty=format:%s"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip().splitlines()
        self.assertIn("chore: update book metadata", subjects)
        self.assertEqual(subjects[0], "chore: bootstrap tracked layout files")

    def test_read_requests_do_not_spam_metadata_commits_when_name_unchanged(self):
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": "book_clean", "book_name": "clean history"},
        )
        self.assertEqual(init_resp.status_code, 200)
        self.assertEqual(self._commit_count("book_clean"), 2)

        for _ in range(4):
            read_resp = self.client.get(
                "/books/get_file",
                query_string={
                    "book_id": "book_clean",
                    "file_name": "world_model.md",
                },
            )
            self.assertEqual(read_resp.status_code, 200)

        self.assertEqual(self._commit_count("book_clean"), 2)

    def test_metadata_commit_occurs_when_book_name_changes(self):
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": "book_rename", "book_name": "old name"},
        )
        self.assertEqual(init_resp.status_code, 200)
        self.assertEqual(self._commit_count("book_rename"), 2)

        read_resp = self.client.post(
            "/books/init",
            json={
                "book_id": "book_rename",
                "book_name": "new name",
            },
        )
        self.assertEqual(read_resp.status_code, 200)
        self.assertEqual(self._commit_count("book_rename"), 3)

    def test_books_init_without_book_id_uses_deterministic_id(self):
        book_name = "三体"
        expected = generate_deterministic_id(book_name)

        first = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["book_id"], expected)

        second = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["book_id"], expected)

        self.assertTrue((self.temp_dir / expected).exists())

    def test_books_init_book_name_accepts_existing_book_id_without_nested_hash(self):
        seed_name = "donk"
        first = self.client.post("/books/init", json={"book_name": seed_name})
        self.assertEqual(first.status_code, 200)
        existing_id = first.get_json()["book_id"]

        second = self.client.post("/books/init", json={"book_name": existing_id})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["book_id"], existing_id)

        nested = generate_deterministic_id(existing_id)
        self.assertNotEqual(nested, existing_id)
        self.assertFalse((self.temp_dir / nested).exists())

    def test_books_search_fuzzy_and_resilient(self):
        self.client.post("/books/init", json={"book_id": "book_alpha", "book_name": "galaxy frontier"})
        self.client.post("/books/init", json={"book_id": "book_beta", "book_name": "deep echo"})

        # broken directory name; search should ignore and continue.
        (self.temp_dir / "bad folder").mkdir(parents=True, exist_ok=True)

        resp = self.client.get("/books/search?query=galaxy")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertGreaterEqual(body["total"], 1)

        ids = [row["book_id"] for row in body["matches"]]
        self.assertIn("book_alpha", ids)

    def test_books_search_missing_query(self):
        resp = self.client.get("/books/search")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "MISSING_FIELD")

    def test_delete_locked_book_marks_pending_and_hides_from_library(self):
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": "locked_case", "book_name": "locked story"},
        )
        self.assertEqual(init_resp.status_code, 200)
        self.assertTrue((self.temp_dir / "locked_case").exists())

        locked_error = PermissionError(32, "locked by test")
        with (
            patch("agents.library.shutil.rmtree", side_effect=locked_error),
            patch("agents.library.os.rmdir", side_effect=locked_error),
            patch("agents.library.os.rename", side_effect=locked_error),
        ):
            delete_resp = self.client.delete("/books/locked_case")
            self.assertEqual(delete_resp.status_code, 200)
            delete_body = delete_resp.get_json()
            self.assertEqual(delete_body["status"], "success")
            self.assertTrue(delete_body["cleanup_pending"])

            marker_path = self.temp_dir / "_pending_delete" / "locked_case.json"
            self.assertTrue(marker_path.exists())
            self.assertTrue((self.temp_dir / "locked_case").exists())

            list_resp = self.client.get("/books/list")
            self.assertEqual(list_resp.status_code, 200)
            listed_ids = [book["book_id"] for book in list_resp.get_json()["books"]]
            self.assertNotIn("locked_case", listed_ids)

            search_resp = self.client.get("/books/search?query=locked")
            self.assertEqual(search_resp.status_code, 200)
            matched_ids = [book["book_id"] for book in search_resp.get_json()["matches"]]
            self.assertNotIn("locked_case", matched_ids)

    def test_delete_book_cancels_active_tomato_background_work_first(self):
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": "active_import", "book_name": "active story"},
        )
        self.assertEqual(init_resp.status_code, 200)
        self.assertTrue((self.temp_dir / "active_import").exists())

        calls: list[str] = []

        def fake_cancel(book_id: str) -> None:
            calls.append(book_id)

        with patch("agents.tomato_import.cancel_book_background_work", side_effect=fake_cancel):
            delete_resp = self.client.delete("/books/active_import")

        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.get_json()["status"], "success")
        self.assertEqual(calls, ["active_import"])
        self.assertFalse((self.temp_dir / "active_import").exists())

    def test_cancel_book_background_work_signals_download_and_stops_shared_client(self):
        from agents import tomato_import

        cancel_event = threading.Event()
        tomato_import._download_cancel_events["active_import"] = cancel_event
        tomato_import._download_progress["active_import"] = {"status": "downloading"}

        with patch("utils.tomato_exe_client.stop_shared_client") as stop_shared_client:
            tomato_import.cancel_book_background_work("active_import")

        self.assertTrue(cancel_event.is_set())
        self.assertNotIn("active_import", tomato_import._download_cancel_events)
        self.assertNotIn("active_import", tomato_import._download_progress)
        stop_shared_client.assert_called_once_with()

    def test_online_download_cancel_during_fallback_returns_cancelled(self):
        from agents import tomato_import

        def fake_fallback_download(book_id: str) -> dict:
            event = tomato_import._download_cancel_events[book_id]
            event.set()
            return {"chapters": []}

        with (
            patch("agents.tomato_import._download_via_exe", return_value=None),
            patch("utils.tomato_search.download_book", side_effect=fake_fallback_download),
        ):
            result = tomato_import._download_online_book("active_import", project_root=str(self.temp_dir))

        self.assertEqual(result, {"cancelled": True, "book_id": "active_import"})
        self.assertNotIn("active_import", tomato_import._download_cancel_events)
        self.assertEqual(tomato_import._download_progress["active_import"]["status"], "cancelled")

    def test_delete_book_removes_conversation_files(self):
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": "conv_cleanup_test", "book_name": "conv book"},
        )
        self.assertEqual(init_resp.status_code, 200)

        created_files = self._write_conversation_runtime("conv_cleanup_test")
        kept_files = self._write_conversation_runtime("conv_cleanup_test_extra", "conv_keep")

        self.assertTrue(all(f.exists() for f in created_files))

        delete_resp = self.client.delete("/books/conv_cleanup_test")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.get_json()["status"], "success")

        for f in created_files:
            self.assertFalse(f.exists(), f"conversation file should be deleted: {f}")
        for f in kept_files:
            self.assertTrue(f.exists(), f"other book conversation file should be preserved: {f}")

    def test_pending_delete_missing_book_clears_conversation_files(self):
        book_id = "pending_conv_cleanup"
        marker_dir = self.temp_dir / "_pending_delete"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker = marker_dir / f"{book_id}.json"
        marker.write_text(json.dumps({"book_id": book_id, "reason": "locked"}, ensure_ascii=False), encoding="utf-8")

        created_files = self._write_conversation_runtime(book_id, "conv_pending")
        self.assertTrue(all(f.exists() for f in created_files))

        delete_resp = self.client.delete(f"/books/{book_id}")
        self.assertEqual(delete_resp.status_code, 200)
        body = delete_resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertFalse(body["cleanup_pending"])
        self.assertFalse(marker.exists())

        for f in created_files:
            self.assertFalse(f.exists(), f"pending-delete conversation file should be deleted: {f}")


if __name__ == "__main__":
    unittest.main()
