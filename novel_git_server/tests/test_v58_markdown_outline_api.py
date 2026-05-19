import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V58MarkdownOutlineApiTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v58_markdown_outline_{uuid.uuid4().hex}"
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

    def _write_markdown(self, repo_dir: Path, file_name: str, content: str) -> None:
        target = repo_dir / file_name
        target.write_text(content, encoding="utf-8")

    def test_get_markdown_outline_returns_canonical_paths(self):
        book_id, repo_dir = self._init_book(book_name="v58_outline")
        self._write_markdown(
            repo_dir,
            "world_model.md",
            (
                "---\n"
                'title: "# not a heading"\n'
                "---\n"
                "# Root\n"
                "## Rule\n"
                "alpha\n"
                "## Rule\n"
                "beta\n"
            ),
        )

        resp = self.client.get(
            "/books/get_markdown_outline",
            query_string={"book_id": book_id, "file_name": "world_model.md"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        outline = body["outline"]

        self.assertEqual([item["title"] for item in outline], ["Root", "Rule", "Rule"])
        self.assertEqual(outline[1]["section_path"], ["Root", "Rule"])
        self.assertEqual(outline[2]["section_path"], ["Root", "Rule [2]"])
        self.assertEqual(outline[0]["heading_line"], 4)

    def test_get_markdown_section_returns_empty_content_length_for_empty_section(self):
        book_id, repo_dir = self._init_book(book_name="v58_empty_section")
        self._write_markdown(
            repo_dir,
            "world_model.md",
            "# Root\n## A\n## B\nbody\n",
        )

        resp = self.client.get(
            "/books/get_markdown_section",
            query_string={
                "book_id": book_id,
                "file_name": "world_model.md",
                "section_path": '["Root","A"]',
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        self.assertEqual(body["content"], "")
        self.assertEqual(body["content_length"], 0)
        self.assertEqual(body["heading_line"], 2)
        self.assertEqual(body["end_line"], 2)

    def test_get_markdown_section_returns_409_for_ambiguous_raw_path(self):
        book_id, repo_dir = self._init_book(book_name="v58_ambiguous")
        self._write_markdown(
            repo_dir,
            "world_model.md",
            "# Root\n## Rule\nalpha\n## Rule\nbeta\n",
        )

        resp = self.client.get(
            "/books/get_markdown_section",
            query_string={
                "book_id": book_id,
                "file_name": "world_model.md",
                "section_path": '["Root","Rule"]',
            },
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["code"], "SECTION_PATH_AMBIGUOUS")

    def test_get_markdown_section_accepts_canonical_path_after_disambiguation(self):
        book_id, repo_dir = self._init_book(book_name="v58_canonical")
        self._write_markdown(
            repo_dir,
            "world_model.md",
            "# Root\n## Rule\nalpha\n## Rule\nbeta\n",
        )

        resp = self.client.get(
            "/books/get_markdown_section",
            query_string={
                "book_id": book_id,
                "file_name": "world_model.md",
                "section_path": '["Root","Rule [2]"]',
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["content"], "beta\n")
        self.assertEqual(body["ordinal"], 2)


if __name__ == "__main__":
    unittest.main()
