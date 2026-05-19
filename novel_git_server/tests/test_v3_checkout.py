import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V3CheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v3_checkout_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _git(self, repo_dir: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def test_include_parsing_and_last_n(self):
        book_id = "book_checkout"
        init_resp = self.client.post(
            "/books/init",
            json={"book_id": book_id, "book_name": "book_checkout"},
        )
        self.assertEqual(init_resp.status_code, 200)
        self.client.post("/commit_world_state", json={"book_id": book_id, "content": "wm"})
        self.client.post("/books/commit_summary", json={"book_id": book_id, "content": "sum"})
        status_seed = self.client.get(
            "/books/get_file",
            query_string={"book_id": book_id, "file_name": "status_card.md"},
        )
        self.assertEqual(status_seed.status_code, 200)
        status_etag = status_seed.get_json()["etag"]
        update_resp = self.client.post(
            "/books/update_file",
            json={
                "book_id": book_id,
                "file_name": "status_card.md",
                "content": "card-state",
                "base_etag": status_etag,
            },
        )
        self.assertEqual(update_resp.status_code, 200)
        self.client.post("/books/add_chapter", json={"book_id": book_id, "chapter_index": 1, "content": "c1"})
        self.client.post("/books/add_chapter", json={"book_id": book_id, "chapter_index": 2, "content": "c2"})
        self.client.post("/books/add_chapter", json={"book_id": book_id, "chapter_index": 3, "content": "c3"})

        resp = self.client.get(
            "/checkout?book_id=book_checkout&include=world_model, summary, status_card, chapters&last_n=2"
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()["payload"]
        self.assertEqual(payload["include"], ["world_model", "summary", "status_card", "chapters"])
        markdown = payload["markdown"]
        self.assertIn("## status_card", markdown)
        self.assertIn("card-state", markdown)
        self.assertIn("## chapter:0002_", markdown)
        self.assertIn("## chapter:0003_", markdown)
        self.assertNotIn("## chapter:0001_", markdown)

    def test_unknown_include_token_returns_400(self):
        resp = self.client.get("/checkout?book_id=book_checkout&include=world_model,unknown")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_add_chapter_returns_commit_id_and_archives_to_book_repo(self):
        book_id = "book_add_chapter_commit"

        resp = self.client.post(
            "/books/add_chapter",
            json={
                "book_id": book_id,
                "chapter_index": 1,
                "content": "# 第1章\n\n内容",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["commit_id"])

        repo_dir = self.temp_dir / book_id
        head = self._git(repo_dir, "rev-parse", "HEAD")
        self.assertEqual(body["commit_id"], head)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")
        self.assertEqual(self._git(repo_dir, "cat-file", "-e", "HEAD:chapters/0001_第1章.md"), "")


if __name__ == "__main__":
    unittest.main()

