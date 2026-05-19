import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V31HighlightsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_highlights_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_chapter(self, book_name: str, content: str, chapter_index: int = 1) -> None:
        resp = self.client.post(
            "/books/add_chapter",
            json={
                "book_name": book_name,
                "chapter_index": chapter_index,
                "content": content,
            },
        )
        self.assertEqual(resp.status_code, 200)

    def test_extract_highlights_returns_char_snippets_with_metadata(self):
        content = "\n".join(
            [
                "开场白",
                "他借了高利贷",
                "流浪汉在街角观察",
                "无关行",
                "另一段",
                "他终于拿下大满贯",
                "结尾",
            ]
        )
        self._seed_chapter("高光主流程", content)

        resp = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "高光主流程",
                "chapter_index": 1,
                "keywords": ["高利贷", "流浪汉", "大满贯"],
                "context_sentences": 0,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["snippet_count"], 2)
        self.assertEqual(body["hit_line_count"], 3)
        self.assertFalse(body["truncated"])
        self.assertEqual(body["context_sentences"], 0)
        self.assertIn("start_char", body["snippets"][0])
        self.assertIn("end_char", body["snippets"][0])
        self.assertIn("hit_offsets", body["snippets"][0])
        self.assertEqual(body["snippets"][0]["hit_line_numbers"], [2, 3])
        self.assertIn("高利贷", body["snippets"][0]["hit_keywords"])

    def test_extract_highlights_merges_adjacent_sentence_windows(self):
        content = "序章。高利贷浮现。过渡段。大满贯转折。尾声。"
        self._seed_chapter("相邻合并", content)

        resp = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "相邻合并",
                "chapter_index": 1,
                "keywords": ["高利贷", "大满贯"],
                "context_sentences": 1,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["snippet_count"], 1)
        self.assertIn("高利贷", body["snippets"][0]["content"])
        self.assertIn("大满贯", body["snippets"][0]["content"])
        self.assertLessEqual(body["snippets"][0]["start_char"], content.find("高利贷"))

    def test_extract_highlights_no_hits_returns_success_empty(self):
        content = "\n".join(["只有日常描写", "没有目标关键词", "结束"])
        self._seed_chapter("无命中场景", content)

        resp = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "无命中场景",
                "chapter_index": 1,
                "keywords": ["不存在的词"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["snippet_count"], 0)
        self.assertEqual(body["hit_line_count"], 0)
        self.assertEqual(body["snippets"], [])
        self.assertIn("未命中关键词", body["message"])

    def test_extract_highlights_preserves_tail_keyword_in_single_line_text(self):
        prefix = "前文铺垫" * 600
        content = prefix + "终局关键词" + ("尾声" * 20)
        self._seed_chapter("单行尾词", content)

        resp = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "单行尾词",
                "chapter_index": 1,
                "keywords": ["终局关键词"],
                "context_sentences": 2,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertGreaterEqual(body["snippet_count"], 1)
        joined = "\n".join(snippet["content"] for snippet in body["snippets"])
        self.assertIn("终局关键词", joined)
        target_snippets = [snippet for snippet in body["snippets"] if "终局关键词" in snippet["content"]]
        self.assertTrue(target_snippets)
        self.assertGreater(target_snippets[0]["start_char"], 0)
        self.assertEqual(target_snippets[0]["hit_line_numbers"], [1])

    def test_extract_highlights_anchor_center_crop_keeps_keyword_under_budget(self):
        content = ("A" * 3200) + "尾部核心关键词" + ("B" * 3200)
        self._seed_chapter("预算锚点", content)

        resp = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "预算锚点",
                "chapter_index": 1,
                "keywords": ["尾部核心关键词"],
                "context_sentences": 6,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["truncated"])
        self.assertEqual(body["total_chars"], 1000)
        self.assertEqual(body["max_total_chars"], 1000)
        self.assertIn("尾部核心关键词", body["snippets"][0]["content"])

    def test_extract_highlights_rejects_invalid_payload(self):
        self._seed_chapter("参数校验", "关键词出现在这里")

        resp2 = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "参数校验",
                "chapter_index": 1,
                "keywords": [],
            },
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.get_json()["code"], "INVALID_PAYLOAD")

        resp3 = self.client.post(
            "/tools/extract_chapter_highlights",
            json={
                "book_name": "参数校验",
                "chapter_index": 1,
                "keywords": ["关键词"],
                "context_sentences": 99,
            },
        )
        self.assertEqual(resp3.status_code, 400)
        self.assertEqual(resp3.get_json()["code"], "INVALID_PAYLOAD")


if __name__ == "__main__":
    unittest.main()
