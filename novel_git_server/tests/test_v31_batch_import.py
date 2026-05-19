import json
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
from utils.book_storage import generate_deterministic_id  # noqa: E402


class V31BatchImportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_batch_import_{uuid.uuid4().hex}"
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

    def test_batch_import_from_list(self):
        payload = {
            "book_id": "batch_list",
            "content": [
                "Chapter 1 Start\nBody A",
                "Chapter 2 Continue\nBody B",
            ],
        }
        resp = self.client.post("/books/batch_import", json=payload)
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["saved_count"], 2)
        self.assertEqual(body["total_parsed"], 2)
        self.assertTrue(body["commit_id"])

        repo_dir = self.temp_dir / "batch_list"
        self.assertEqual(body["commit_id"], self._git(repo_dir, "rev-parse", "HEAD"))
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        chapter_dir = repo_dir / "chapters"
        names = sorted(p.name for p in chapter_dir.glob("*.md"))
        self.assertEqual(len(names), 2)
        self.assertTrue(names[0].startswith("0001_"))
        self.assertTrue(names[1].startswith("0002_"))

    def test_append_after_existing_chapters(self):
        book_id = "append_case"
        for idx in range(1, 4):
            r = self.client.post(
                "/books/add_chapter",
                json={"book_id": book_id, "chapter_index": idx, "content": f"Chapter {idx} Existing"},
            )
            self.assertEqual(r.status_code, 200)

        repo_dir = self.temp_dir / book_id
        commit_count_before = int(self._git(repo_dir, "rev-list", "--count", "HEAD"))
        batch_text = "Chapter 4 New A\nBody A\n|||CHAPTER_START|||\nChapter 5 New B\nBody B"
        resp = self.client.post(
            "/books/batch_import",
            json={
                "book_id": book_id,
                "content": batch_text,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["saved_count"], 2)
        self.assertEqual(body["total_parsed"], 2)
        self.assertTrue(body["commit_id"])
        self.assertEqual(body["commit_id"], self._git(repo_dir, "rev-parse", "HEAD"))
        self.assertEqual(int(self._git(repo_dir, "rev-list", "--count", "HEAD")), commit_count_before + 1)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        chapter_dir = repo_dir / "chapters"
        names = sorted(p.name for p in chapter_dir.glob("*.md"))
        self.assertEqual(len(names), 5)
        self.assertTrue(any(name.startswith("0004_") for name in names))
        self.assertTrue(any(name.startswith("0005_") for name in names))

    def test_batch_import_without_book_id_uses_deterministic_id(self):
        book_name = "三体"
        expected_book_id = generate_deterministic_id(book_name)
        payload = {
            "book_name": book_name,
            "content": [
                "Chapter 1 Era A\nBody A",
                "Chapter 2 Era B\nBody B",
            ],
        }
        resp = self.client.post("/books/batch_import", json=payload)
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertEqual(body["book_id"], expected_book_id)
        self.assertTrue(body["commit_id"])

        repo_dir = self.temp_dir / expected_book_id
        self.assertEqual(body["commit_id"], self._git(repo_dir, "rev-parse", "HEAD"))
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        chapter_dir = repo_dir / "chapters"
        self.assertTrue(chapter_dir.exists())

        metadata_path = repo_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["book_name"], book_name)

    def test_batch_import_self_heals_deleted_book_dir(self):
        book_name = "same_name_revival"
        expected_book_id = generate_deterministic_id(book_name)

        first = self.client.post(
            "/books/batch_import",
            json={
                "book_name": book_name,
                "content": "Chapter 1 First\nBody 1",
            },
        )
        self.assertEqual(first.status_code, 200)

        book_dir = self.temp_dir / expected_book_id
        tomb_dir = self.temp_dir / f"{expected_book_id}_deleted"
        if tomb_dir.exists():
            shutil.rmtree(tomb_dir, ignore_errors=True)
        shutil.move(str(book_dir), str(tomb_dir))
        self.assertFalse(book_dir.exists())

        second = self.client.post(
            "/books/batch_import",
            json={
                "book_name": book_name,
                "content": "Chapter 1 Reborn\nBody 2",
            },
        )
        self.assertEqual(second.status_code, 200)

        body = second.get_json()
        self.assertEqual(body["book_id"], expected_book_id)
        self.assertTrue(body["commit_id"])
        self.assertTrue(book_dir.exists())
        self.assertTrue((book_dir / "chapters").exists())
        self.assertTrue((book_dir / "metadata.json").exists())
        self.assertEqual(body["commit_id"], self._git(book_dir, "rev-parse", "HEAD"))
        self.assertEqual(self._git(book_dir, "status", "--short"), "")


if __name__ == "__main__":
    unittest.main()
