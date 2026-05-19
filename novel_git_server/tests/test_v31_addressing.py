import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.book_storage import generate_deterministic_id  # noqa: E402


class V31AddressingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_addressing_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_world_state_commit_with_book_name(self):
        book_name = "三体"
        expected_id = generate_deterministic_id(book_name)

        resp = self.client.post("/commit_world_state", json={"book_name": book_name, "content": "# world"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["book_id"], expected_id)

        book_dir = self.temp_dir / expected_id
        self.assertTrue((book_dir / "world_model.md").exists())
        self.assertTrue((book_dir / "style_guide.md").exists())
        self.assertTrue((book_dir / "status_card.md").exists())
        self.assertTrue((book_dir / "error_archive.md").exists())
        self.assertEqual((book_dir / "style_guide.md").read_text(encoding="utf-8"), "# 文风指南\n\n")
        self.assertIn("下一章约束", (book_dir / "status_card.md").read_text(encoding="utf-8"))
        self.assertEqual((book_dir / "error_archive.md").read_text(encoding="utf-8"), "# 错误档案\n\n")

    def test_summary_commit_with_book_name(self):
        book_name = "银河帝国"
        expected_id = generate_deterministic_id(book_name)

        resp = self.client.post("/books/commit_summary", json={"book_name": book_name, "content": "# summary"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["book_id"], expected_id)
        self.assertTrue((self.temp_dir / expected_id / "summary.md").exists())

    def test_self_heal_after_manual_delete(self):
        book_name = "自愈测试"
        expected_id = generate_deterministic_id(book_name)

        first = self.client.post("/commit_world_state", json={"book_name": book_name, "content": "# first"})
        self.assertEqual(first.status_code, 200)

        book_dir = self.temp_dir / expected_id
        tomb_dir = self.temp_dir / f"{expected_id}_deleted"
        if tomb_dir.exists():
            shutil.rmtree(tomb_dir, ignore_errors=True)
        shutil.move(str(book_dir), str(tomb_dir))
        self.assertFalse(book_dir.exists())

        second = self.client.post("/commit_world_state", json={"book_name": book_name, "content": "# second"})
        self.assertEqual(second.status_code, 200)

        self.assertTrue(book_dir.exists())
        self.assertTrue((book_dir / "style_guide.md").exists())
        self.assertEqual((book_dir / "style_guide.md").read_text(encoding="utf-8"), "# 文风指南\n\n")
        self.assertTrue((book_dir / "status_card.md").exists())
        self.assertTrue((book_dir / "error_archive.md").exists())
        self.assertIn("当前创作运行态", (book_dir / "status_card.md").read_text(encoding="utf-8"))
        self.assertEqual((book_dir / "error_archive.md").read_text(encoding="utf-8"), "# 错误档案\n\n")

    def test_add_chapter_uses_existing_id_when_book_name_is_id(self):
        init_resp = self.client.post("/books/init", json={"book_name": "donk"})
        self.assertEqual(init_resp.status_code, 200)
        existing_id = init_resp.get_json()["book_id"]

        save_resp = self.client.post(
            "/books/add_chapter",
            json={
                "book_name": existing_id,
                "chapter_index": 1,
                "content": "test body",
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        body = save_resp.get_json()
        self.assertEqual(body["book_id"], existing_id)
        self.assertTrue((self.temp_dir / existing_id / "chapters").exists())


if __name__ == "__main__":
    unittest.main()
