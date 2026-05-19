import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.chapter_length import measure_chapter_lengths, split_chapter_spans  # noqa: E402


class V65ChapterLengthToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v65_chapter_length_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _init_book(self, *, book_name: str) -> tuple[str, Path]:
        resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        book_id = body["book_id"]
        return book_id, self.temp_dir / book_id

    def test_split_chapter_spans_handles_atx_and_bare_chapter_titles(self):
        markdown = (
            "# 续写草稿\n\n"
            "## 第156章 决赛对阵G2\n"
            "第一章正文。\n"
            "```md\n"
            "## 第999章 代码块里不算章节\n"
            "```\n"
            "第157章 捧杯时刻\n"
            "第二章正文。\n"
        )

        spans = split_chapter_spans(markdown)

        self.assertEqual([span.title for span in spans], ["第156章 决赛对阵G2", "第157章 捧杯时刻"])
        self.assertIn("代码块里不算章节", spans[0].content)
        self.assertEqual(spans[1].content.strip(), "第二章正文。")

    def test_measure_chapter_lengths_returns_deficits(self):
        markdown = "## 第1章 短章\n一句话。\n## 第2章 达标\n" + ("正文" * 1200) + "\n"

        result = measure_chapter_lengths(markdown, min_chars=10, target_chars=20, max_chars=3000)

        self.assertFalse(result["ok"])
        self.assertEqual(result["chapter_count"], 2)
        self.assertEqual(result["under_min_count"], 1)
        self.assertEqual(result["chapters"][0]["status"], "under_min")
        self.assertGreater(result["chapters"][0]["deficit_to_min"], 0)
        self.assertEqual(result["chapters"][1]["status"], "ok")

    def test_validate_chapter_lengths_endpoint_is_read_only_and_reports_current_draft(self):
        book_id, repo_dir = self._init_book(book_name="v65_length_endpoint")
        draft = (
            "# 续写草稿\n\n"
            "## 第156章 决赛对阵G2\n"
            "短。\n"
            "## 第157章 捧杯时刻\n"
            + ("正文" * 1200)
            + "\n"
        )
        draft_path = repo_dir / "chapter_draft.md"
        draft_path.write_text(draft, encoding="utf-8")

        resp = self.client.post(
            "/tools/validate_chapter_lengths",
            json={
                "book_id": book_id,
                "file_name": "chapter_draft.md",
                "min_chars": 10,
                "target_chars": 20,
                "max_chars": 3000,
            },
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["file_name"], "chapter_draft.md")
        self.assertFalse(body["ok"])
        self.assertEqual([chapter["title"] for chapter in body["chapters"]], ["第156章 决赛对阵G2", "第157章 捧杯时刻"])
        self.assertEqual(body["chapters"][0]["status"], "under_min")
        self.assertEqual(draft_path.read_text(encoding="utf-8"), draft)

    def test_validate_chapter_lengths_rejects_path_escape(self):
        book_id, _repo_dir = self._init_book(book_name="v65_length_escape")

        resp = self.client.post(
            "/tools/validate_chapter_lengths",
            json={"book_id": book_id, "file_name": "../chapter_draft.md"},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")


if __name__ == "__main__":
    unittest.main()
