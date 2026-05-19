import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.book_storage import generate_deterministic_id  # noqa: E402


class V31ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_archive_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _latest_subject(self, book_id: str) -> str:
        repo_dir = self.temp_dir / book_id
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    def _commit_count(self, book_id: str) -> int:
        repo_dir = self.temp_dir / book_id
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return int(result.stdout.strip())

    def _get_file_etag(self, *, file_name: str, book_name: str | None = None, book_id: str | None = None) -> str:
        params: dict[str, str] = {"file_name": file_name}
        if book_name is not None:
            params["book_name"] = book_name
        if book_id is not None:
            params["book_id"] = book_id
        resp = self.client.get("/books/get_file", query_string=params)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("etag"))
        self.assertEqual(resp.headers.get("ETag"), body["etag"])
        return body["etag"]

    def test_update_file_default_origin_uses_system_prefix(self):
        book_name = "归档测试"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="status_card.md", book_name=book_name)

        resp = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "# card\nA",
                "base_etag": etag,
                "message": "refresh card",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["book_id"], book_id)

        subject = self._latest_subject(book_id)
        self.assertTrue(subject.startswith("[System_Update]"))

    def test_update_file_origin_prefixes(self):
        book_name = "标签测试"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="error_archive.md", book_name=book_name)

        r1 = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "error_archive.md",
                "content": "# e1",
                "base_etag": etag,
                "origin": "ai",
                "message": "ai pass",
            },
        )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(self._latest_subject(book_id).startswith("[AI_Update]"))

        etag2 = r1.get_json()["etag"]
        r2 = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "error_archive.md",
                "content": "# e2",
                "base_etag": etag2,
                "origin": "user",
                "message": "user pass",
            },
        )
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(self._latest_subject(book_id).startswith("[User_Edit]"))

    def test_update_file_no_changes_short_circuits_commit(self):
        book_name = "无变更测试"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="status_card.md", book_name=book_name)

        first = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "# same-content",
                "base_etag": etag,
                "message": "first write",
            },
        )
        self.assertEqual(first.status_code, 200)
        count_before = self._commit_count(book_id)
        etag2 = first.get_json()["etag"]

        second = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "# same-content",
                "base_etag": etag2,
                "message": "second write",
            },
        )
        self.assertEqual(second.status_code, 200)
        body = second.get_json()
        self.assertIn("No changes detected", body.get("message", ""))
        self.assertEqual(self._commit_count(book_id), count_before)

    def test_path_traversal_is_blocked(self):
        resp = self.client.post(
            "/books/update_file",
            json={
                "book_name": "安全测试",
                "file_name": "../escape.md",
                "content": "x",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

        resp2 = self.client.get("/books/get_file?book_name=%E5%AE%89%E5%85%A8%E6%B5%8B%E8%AF%95&file_name=../escape.md")
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.get_json()["code"], "INVALID_PAYLOAD")

    def test_get_file_can_read_chapter_markdown(self):
        book_name = "章节读取"

        save = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapters/0001_demo.md",
                "content": "chapter body",
                "message": "seed chapter",
            },
        )
        self.assertEqual(save.status_code, 200)

        read = self.client.get(
            "/books/get_file?book_name=%E7%AB%A0%E8%8A%82%E8%AF%BB%E5%8F%96&file_name=chapters/0001_demo.md"
        )
        self.assertEqual(read.status_code, 200)
        body = read.get_json()
        self.assertEqual(body["content"], "chapter body")

    def test_list_hot_files_returns_core_and_chapters(self):
        book_name = "热文件列表"
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapters/0007_demo.md",
                "content": "line-1\nline-2\n",
                "message": "seed chapter for hot list",
            },
        )
        self.assertEqual(seed.status_code, 200)

        resp = self.client.get(
            "/books/list_hot_files",
            query_string={"book_name": book_name},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(isinstance(body.get("files"), list) and body["files"])

        names = [item["file_name"] for item in body["files"]]
        self.assertIn("world_model.md", names)
        self.assertIn("status_card.md", names)
        self.assertIn("summary.md", names)
        self.assertIn("chapter_draft.md", names)
        self.assertIn("chapters/0007_demo.md", names)

        draft_row = next(item for item in body["files"] if item["file_name"] == "chapter_draft.md")
        self.assertEqual(draft_row["file_type"], "chapter")
        self.assertTrue(draft_row["virtual"])

        chapter_row = next(item for item in body["files"] if item["file_name"] == "chapters/0007_demo.md")
        self.assertEqual(chapter_row["file_type"], "chapter")

    def test_get_archive_range_reads_utf8_line_window(self):
        book_name = "范围读取"
        etag = self._get_file_etag(file_name="summary.md", book_name=book_name)
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "content": "第一行\n第二行\n第三行\n第四行\n",
                "base_etag": etag,
                "message": "seed range file",
            },
        )
        self.assertEqual(seed.status_code, 200)

        read = self.client.get(
            "/books/get_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "summary.md",
                "start_line": 2,
                "end_line": 3,
            },
        )
        self.assertEqual(read.status_code, 200)
        body = read.get_json()
        self.assertEqual(body["content"], "第二行\n第三行\n")
        self.assertEqual(body["line_count"], 2)
        self.assertEqual(body["total_lines"], 4)
        self.assertEqual(body["returned_end_line"], 3)
        self.assertEqual(body["max_lines"], 500)

    def test_get_archive_range_rejects_invalid_window(self):
        resp = self.client.get(
            "/books/get_archive_range",
            query_string={
                "book_name": "窗口校验",
                "file_name": "summary.md",
                "start_line": 8,
                "end_line": 3,
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("end_line", body["message"])

    def test_get_archive_range_enforces_max_lines_cap(self):
        resp = self.client.get(
            "/books/get_archive_range",
            query_string={
                "book_name": "上限校验",
                "file_name": "summary.md",
                "start_line": 1,
                "end_line": 501,
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertEqual(
            body["message"],
            "请求行数（501行）超过上限（500行），请通过多次分段读取实现。",
        )

    def test_get_archive_range_blocks_path_traversal(self):
        resp = self.client.get(
            "/books/get_archive_range",
            query_string={
                "book_name": "范围安全",
                "file_name": "../escape.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_get_cold_archive_range_reads_from_chapters_and_root_fallback(self):
        book_name = "冷档案读取"

        seed_chapter = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapters/0123_demo.md",
                "content": "第一行\n第二行\n第三行\n第四行\n",
            },
        )
        self.assertEqual(seed_chapter.status_code, 200)

        chapter_read = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "0123_demo.md",
                "start_line": 2,
                "end_line": 3,
            },
        )
        self.assertEqual(chapter_read.status_code, 200)
        chapter_body = chapter_read.get_json()
        self.assertEqual(chapter_body["content"], "第二行\n第三行\n")
        self.assertEqual(chapter_body["file_name"], "chapters/0123_demo.md")
        self.assertEqual(chapter_body["real_file_name"], "0123_demo.md")
        self.assertEqual(chapter_body["total_lines"], 4)
        self.assertNotIn("etag", chapter_body)
        self.assertIsNone(chapter_read.headers.get("ETag"))

        seed_root = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "0124_root.md",
                "content": "A\nB\nC\n",
            },
        )
        self.assertEqual(seed_root.status_code, 200)

        root_read = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "0124_root.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(root_read.status_code, 200)
        root_body = root_read.get_json()
        self.assertEqual(root_body["content"], "A\nB\n")
        self.assertEqual(root_body["file_name"], "0124_root.md")
        self.assertEqual(root_body["real_file_name"], "0124_root.md")
        self.assertNotIn("etag", root_body)
        self.assertIsNone(root_read.headers.get("ETag"))

    def test_get_cold_archive_range_numeric_prefix_fallback_hits_chapter(self):
        book_name = "冷档案前缀命中"
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapters/0095_第95章_风暴前夜.md",
                "content": "命中行A\n命中行B\n",
            },
        )
        self.assertEqual(seed.status_code, 200)

        for query_name in ("95.md", "chapter95", "095"):
            read = self.client.get(
                "/books/get_cold_archive_range",
                query_string={
                    "book_name": book_name,
                    "file_name": query_name,
                    "start_line": 1,
                    "end_line": 2,
                },
            )
            self.assertEqual(read.status_code, 200, msg=f"query={query_name}")
            body = read.get_json()
            self.assertEqual(body["content"], "命中行A\n命中行B\n")
            self.assertEqual(body["file_name"], "chapters/0095_第95章_风暴前夜.md")
            self.assertEqual(body["real_file_name"], "0095_第95章_风暴前夜.md")

    def test_get_cold_archive_range_rejects_blacklisted_core_files(self):
        resp = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": "冷档案黑名单",
                "file_name": "summary.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("forbidden", body["message"])

    def test_get_cold_archive_range_rejects_invalid_filename_pattern(self):
        resp = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": "冷档案正则",
                "file_name": "notes.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "INVALID_PAYLOAD")
        self.assertIn("chapter_*.md", body["message"])

    def test_get_cold_archive_range_blocks_path_traversal(self):
        resp = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": "冷档案安全",
                "file_name": "../0123_demo.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_get_cold_archive_range_truncates_over_limit_requests(self):
        book_name = "冷档案截断"
        long_content = "".join(f"第{i}行\n" for i in range(1, 161))
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapters/0125_long.md",
                "content": long_content,
            },
        )
        self.assertEqual(seed.status_code, 200)

        read = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "0125_long.md",
                "start_line": 1,
                "end_line": 200,
            },
        )
        self.assertEqual(read.status_code, 200)
        body = read.get_json()
        self.assertEqual(body["line_count"], 100)
        self.assertEqual(body["returned_end_line"], 100)
        self.assertEqual(body["max_lines"], 100)
        self.assertIn("超过上限", body["message"])

    def test_get_cold_archive_range_smooths_end_line_beyond_eof(self):
        book_name = "冷档案越界"
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "chapter_demo_tail.md",
                "content": "甲\n乙\n丙\n",
            },
        )
        self.assertEqual(seed.status_code, 200)

        read = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "chapter_demo_tail.md",
                "start_line": 2,
                "end_line": 99,
            },
        )
        self.assertEqual(read.status_code, 200)
        body = read.get_json()
        self.assertEqual(body["content"], "乙\n丙\n")
        self.assertEqual(body["returned_end_line"], 3)
        self.assertIn("平滑截断", body["message"])

    def test_append_file_appends_content_and_commits(self):
        book_name = "增量追加"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="summary.md", book_name=book_name)

        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "content": "头部",
                "base_etag": etag,
                "message": "seed summary",
            },
        )
        self.assertEqual(seed.status_code, 200)
        count_before = self._commit_count(book_id)
        etag2 = seed.get_json()["etag"]

        appended = self.client.post(
            "/books/append_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "append_content": "\n尾部增量",
                "base_etag": etag2,
                "message": "append summary",
            },
        )
        self.assertEqual(appended.status_code, 200)
        body = appended.get_json()
        self.assertEqual(body["appended_chars"], len("\n尾部增量"))
        self.assertGreater(body["new_size"], len("头部"))
        self.assertTrue(body.get("commit_id"))

        read = self.client.get(
            "/books/get_file",
            query_string={
                "book_name": book_name,
                "file_name": "summary.md",
            },
        )
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.get_json()["content"], "头部\n尾部增量")
        self.assertEqual(self._commit_count(book_id), count_before + 1)

    def test_append_file_empty_content_short_circuits(self):
        book_name = "空追加"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="status_card.md", book_name=book_name)
        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "初始内容",
                "base_etag": etag,
            },
        )
        self.assertEqual(seed.status_code, 200)
        count_before = self._commit_count(book_id)

        resp = self.client.post(
            "/books/append_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "append_content": "",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["appended_chars"], 0)
        self.assertIn("unchanged", body["message"])
        self.assertIsNone(body["commit_id"])
        self.assertEqual(self._commit_count(book_id), count_before)

    def test_append_file_blocks_path_traversal(self):
        resp = self.client.post(
            "/books/append_file",
            json={
                "book_name": "追加安全",
                "file_name": "../escape.md",
                "append_content": "x",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_get_file_returns_etag(self):
        book_name = "etag读取"
        resp = self.client.get(
            "/books/get_file",
            query_string={
                "book_name": book_name,
                "file_name": "world_model.md",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("etag"))
        self.assertEqual(resp.headers.get("ETag"), body["etag"])

    def test_get_archive_range_returns_etag(self):
        book_name = "etag范围读取"
        read = self.client.get(
            "/books/get_archive_range",
            query_string={
                "book_name": book_name,
                "file_name": "summary.md",
                "start_line": 1,
                "end_line": 2,
            },
        )
        self.assertEqual(read.status_code, 200)
        body = read.get_json()
        self.assertTrue(body.get("etag"))
        self.assertEqual(read.headers.get("ETag"), body["etag"])

    def test_update_file_requires_base_etag_for_core_file(self):
        resp = self.client.post(
            "/books/update_file",
            json={
                "book_name": "核心强校验",
                "file_name": "world_model.md",
                "content": "x",
            },
        )
        self.assertEqual(resp.status_code, 428)
        body = resp.get_json()
        self.assertEqual(body["code"], "PRECONDITION_REQUIRED")
        self.assertIn("base_etag", body["message"])

    def test_update_file_allows_non_core_without_base_etag(self):
        resp = self.client.post(
            "/books/update_file",
            json={
                "book_name": "章节兼容",
                "file_name": "chapters/0009_demo.md",
                "content": "chapter",
            },
        )
        self.assertEqual(resp.status_code, 200)

    def test_update_file_stale_etag_returns_conflict_with_draft(self):
        book_name = "冲突更新"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="world_model.md", book_name=book_name)

        first = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "world_model.md",
                "content": "# world-v1",
                "base_etag": etag,
            },
        )
        self.assertEqual(first.status_code, 200)

        stale_write = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "world_model.md",
                "content": "# world-stale-ai",
                "base_etag": etag,
            },
        )
        self.assertEqual(stale_write.status_code, 409)
        body = stale_write.get_json()
        self.assertEqual(body["code"], "WRITE_CONFLICT")
        self.assertIn("draft_file", body)
        draft_path = Path(body["draft_file"])
        self.assertTrue(draft_path.exists())
        self.assertIn("conflicts", body["draft_file"])
        self.assertIn(".ai_conflict_draft.md", draft_path.name)
        self.assertEqual(body["base_etag"], etag)
        self.assertNotEqual(body["current_etag"], etag)
        self.assertTrue(str(draft_path).startswith(str(self.temp_dir / book_id)))

    def test_append_file_stale_etag_returns_conflict_with_draft(self):
        book_name = "冲突追加"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="summary.md", book_name=book_name)

        first = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "content": "base",
                "base_etag": etag,
            },
        )
        self.assertEqual(first.status_code, 200)

        stale_append = self.client.post(
            "/books/append_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "append_content": "\nAI stale append",
                "base_etag": etag,
            },
        )
        self.assertEqual(stale_append.status_code, 409)
        body = stale_append.get_json()
        self.assertEqual(body["code"], "WRITE_CONFLICT")
        draft_path = Path(body["draft_file"])
        self.assertTrue(draft_path.exists())
        self.assertIn("conflicts", body["draft_file"])
        self.assertEqual(body["base_etag"], etag)
        self.assertNotEqual(body["current_etag"], etag)
        self.assertTrue(str(draft_path).startswith(str(self.temp_dir / book_id)))

    def test_prepend_file_injects_head_and_etag_guard(self):
        book_name = "头部注入"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="world_model.md", book_name=book_name)

        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "world_model.md",
                "content": "原始内容",
                "base_etag": etag,
            },
        )
        self.assertEqual(seed.status_code, 200)
        stale_etag = seed.get_json()["etag"]

        prepend = self.client.post(
            "/books/prepend_file",
            json={
                "book_name": book_name,
                "file_name": "world_model.md",
                "prepend_content": "新设定在最前",
                "base_etag": stale_etag,
                "message": "prepend world model",
            },
        )
        self.assertEqual(prepend.status_code, 200)
        prepend_body = prepend.get_json()
        self.assertGreater(prepend_body["prepended_chars"], 0)

        read = self.client.get(
            "/books/get_file",
            query_string={"book_name": book_name, "file_name": "world_model.md"},
        )
        self.assertEqual(read.status_code, 200)
        content = read.get_json()["content"]
        self.assertTrue(content.startswith("新设定在最前\n\n原始内容"))

        conflict = self.client.post(
            "/books/prepend_file",
            json={
                "book_name": book_name,
                "file_name": "world_model.md",
                "prepend_content": "过期写入",
                "base_etag": stale_etag,
            },
        )
        self.assertEqual(conflict.status_code, 409)
        conflict_body = conflict.get_json()
        self.assertEqual(conflict_body["code"], "WRITE_CONFLICT")
        draft_path = Path(conflict_body["draft_file"])
        self.assertTrue(draft_path.exists())
        self.assertIn("conflicts", conflict_body["draft_file"])
        self.assertTrue(str(draft_path).startswith(str(self.temp_dir / book_id)))

    def test_prepend_file_whitespace_short_circuits(self):
        book_name = "空白头部"
        book_id = generate_deterministic_id(book_name)
        etag = self._get_file_etag(file_name="summary.md", book_name=book_name)

        seed = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "content": "base",
                "base_etag": etag,
            },
        )
        self.assertEqual(seed.status_code, 200)
        count_before = self._commit_count(book_id)

        resp = self.client.post(
            "/books/prepend_file",
            json={
                "book_name": book_name,
                "file_name": "summary.md",
                "prepend_content": "   \n\t",
                "base_etag": seed.get_json()["etag"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["prepended_chars"], 0)
        self.assertIn("unchanged", body["message"])
        self.assertIsNone(body["commit_id"])
        self.assertEqual(self._commit_count(book_id), count_before)

    def test_update_file_returns_warning_when_rollback_fails(self):
        book_id = generate_deterministic_id("回滚失败测试")
        target_rel = "chapters/0002_fail.md"
        target_abs = (self.temp_dir / book_id / "chapters" / "0002_fail.md").resolve()

        def fake_run_git(_repo_dir, args):
            command = args[0] if args else ""
            if command == "status":
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=0,
                    stdout="M  chapters/0002_fail.md\n",
                    stderr="",
                )
            if command == "commit":
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["git", "commit"],
                    stderr="fatal: commit failed",
                )
            return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="", stderr="")

        real_remove = os.remove

        def flaky_remove(path):
            if Path(path).resolve() == target_abs:
                raise OSError("file is locked")
            return real_remove(path)

        with patch("agents.archive.run_git", side_effect=fake_run_git), patch(
            "agents.archive.is_nothing_to_commit_error", return_value=False
        ), patch("agents.archive.os.remove", side_effect=flaky_remove):
            resp = self.client.post(
                "/books/update_file",
                json={
                    "book_id": book_id,
                    "file_name": target_rel,
                    "content": "rollback warning payload",
                    "message": "force fail",
                },
            )

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertEqual(body["code"], "GIT_COMMIT_FAILED")
        self.assertIn("warning", body)
        self.assertIn("rollback_failed", body["warning"])


if __name__ == "__main__":
    unittest.main()
