import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V3ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v3_validation_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_book_id_returns_400(self):
        r1 = self.client.get("/checkout")
        self.assertEqual(r1.status_code, 400)
        self.assertEqual(r1.get_json()["code"], "MISSING_FIELD")

        r2 = self.client.post(
            "/books/add_chapter",
            json={"chapter_index": 1, "content": "x"},
        )
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.get_json()["code"], "MISSING_FIELD")

    def test_invalid_book_id_returns_400(self):
        resp = self.client.post(
            "/commit_world_state",
            json={"book_id": "../escape", "content": "abc"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "MISSING_FIELD")


if __name__ == "__main__":
    unittest.main()

