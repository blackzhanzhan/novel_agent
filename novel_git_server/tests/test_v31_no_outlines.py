import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V31NoOutlinesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_no_outlines_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_does_not_create_legacy_outlines_directory_but_creates_outline_docs(self):
        resp = self.client.post("/books/init", json={"book_id": "book_no_outline", "book_name": "A"})
        self.assertEqual(resp.status_code, 200)

        book_dir = self.temp_dir / "book_no_outline"
        self.assertTrue((book_dir / "chapters").is_dir())
        self.assertFalse((book_dir / "outlines").exists())
        self.assertTrue((book_dir / "brainstorm.md").exists())
        self.assertTrue((book_dir / "master_outline.md").exists())
        self.assertTrue((book_dir / "arc_outline.md").exists())
        self.assertTrue((book_dir / "chapter_outline.md").exists())

    def test_outline_routes_are_removed(self):
        resp_post = self.client.post("/books/save_outline", json={"book_id": "x", "content": "y"})
        resp_get = self.client.get("/books/outlines?book_id=x")
        self.assertEqual(resp_post.status_code, 404)
        self.assertEqual(resp_get.status_code, 404)


if __name__ == "__main__":
    unittest.main()
