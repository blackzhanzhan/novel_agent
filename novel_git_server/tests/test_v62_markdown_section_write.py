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


class V62MarkdownSectionWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v62_markdown_section_write_{uuid.uuid4().hex}"
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

    def _commit_markdown(self, repo_dir: Path, file_name: str, message: str) -> None:
        subprocess.run(["git", "add", "--", file_name], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", message, "--", file_name], cwd=repo_dir, check=True)

    def _read_etag(self, book_id: str, file_name: str) -> str:
        resp = self.client.get(
            "/books/get_file",
            query_string={"book_id": book_id, "file_name": file_name},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()["etag"]

    def _git_show(self, repo_dir: Path, ref: str, file_name: str) -> str:
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_name}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_sync_markdown_sections_replaces_target_section_in_draft_branch(self):
        book_id, repo_dir = self._init_book(book_name="v62_replace_section")
        original = "# Root\n## Alpha\nalpha\n## Beta\nbeta\n"
        self._write_markdown(repo_dir, "chapter_outline.md", original)
        base_etag = self._read_etag(book_id, "chapter_outline.md")

        resp = self.client.post(
            "/api/draft/sync_markdown_sections",
            json={
                "book_id": book_id,
                "message": "replace beta section",
                "origin": "explicit_user_write",
                "writes": [
                    {
                        "file_name": "chapter_outline.md",
                        "op": "replace_section",
                        "section_path": ["Root", "Beta"],
                        "content": "## Beta\nupdated beta\n",
                        "base_etag": base_etag,
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["branch"], "draft/sandbox")
        self.assertTrue(body["commit_id"])

        draft_content = self._git_show(repo_dir, "draft/sandbox", "chapter_outline.md")
        self.assertEqual(draft_content, "# Root\n## Alpha\nalpha\n## Beta\nupdated beta\n")

        mainline_content = self._git_show(repo_dir, body["mainline_branch"], "chapter_outline.md")
        self.assertEqual(mainline_content, original)

    def test_sync_markdown_sections_appends_under_parent_before_next_sibling(self):
        book_id, repo_dir = self._init_book(book_name="v62_append_section")
        original = "# Root\n## Parent\n### Child\nchild\n## Sibling\nrest\n"
        self._write_markdown(repo_dir, "arc_outline.md", original)
        base_etag = self._read_etag(book_id, "arc_outline.md")

        resp = self.client.post(
            "/api/draft/sync_markdown_sections",
            json={
                "book_id": book_id,
                "message": "append child section",
                "origin": "explicit_user_write",
                "writes": [
                    {
                        "file_name": "arc_outline.md",
                        "op": "append_under_section",
                        "section_path": ["Root", "Parent"],
                        "content": "### Added\nnew content\n",
                        "base_etag": base_etag,
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")

        draft_content = self._git_show(repo_dir, "draft/sandbox", "arc_outline.md")
        self.assertEqual(
            draft_content,
            "# Root\n## Parent\n### Child\nchild\n### Added\nnew content\n## Sibling\nrest\n",
        )

    def test_sync_markdown_sections_requires_explicit_write_origin(self):
        book_id, repo_dir = self._init_book(book_name="v62_requires_write_origin")
        original = "# Root\n## Beta\nbeta\n"
        self._write_markdown(repo_dir, "chapter_outline.md", original)
        base_etag = self._read_etag(book_id, "chapter_outline.md")

        resp = self.client.post(
            "/api/draft/sync_markdown_sections",
            json={
                "book_id": book_id,
                "message": "model attempted a write without user write origin",
                "writes": [
                    {
                        "file_name": "chapter_outline.md",
                        "op": "replace_section",
                        "section_path": ["Root", "Beta"],
                        "content": "## Beta\nshould not write\n",
                        "base_etag": base_etag,
                    }
                ],
            },
        )

        self.assertEqual(resp.status_code, 428)
        self.assertEqual(resp.get_json()["code"], "WRITE_INTENT_REQUIRED")
        self.assertEqual((repo_dir / "chapter_outline.md").read_text(encoding="utf-8"), original)

    def test_flat_replace_markdown_section_reuses_section_write_transaction(self):
        book_id, repo_dir = self._init_book(book_name="v62_flat_replace")
        original = "# Root\n## Voice\nplain\n"
        self._write_markdown(repo_dir, "style_guide.md", original)
        base_etag = self._read_etag(book_id, "style_guide.md")

        resp = self.client.post(
            "/api/draft/replace_markdown_section",
            json={
                "book_id": book_id,
                "file_name": "style_guide.md",
                "section_path": "Root > Voice",
                "content": "## Voice\nsentences should carry clipped rhythm.\n",
                "base_etag": base_etag,
                "origin": "explicit_user_write",
                "message": "replace style voice section",
            },
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["updated_files"][0]["file_name"], "style_guide.md")
        draft_content = self._git_show(repo_dir, "draft/sandbox", "style_guide.md")
        self.assertEqual(draft_content, "# Root\n## Voice\nsentences should carry clipped rhythm.\n")
        self.assertEqual(self._git_show(repo_dir, body["mainline_branch"], "style_guide.md"), original)

    def test_flat_append_markdown_section_requires_explicit_write_origin(self):
        book_id, repo_dir = self._init_book(book_name="v62_flat_append_origin")
        original = "# Root\n## Voice\nplain\n"
        self._write_markdown(repo_dir, "style_guide.md", original)
        base_etag = self._read_etag(book_id, "style_guide.md")

        resp = self.client.post(
            "/api/draft/append_markdown_section",
            json={
                "book_id": book_id,
                "file_name": "style_guide.md",
                "section_path": ["Root", "Voice"],
                "content": "### Image Grammar\nUse hard tactile nouns.\n",
                "base_etag": base_etag,
                "message": "append style section without origin",
            },
        )

        self.assertEqual(resp.status_code, 428)
        self.assertEqual(resp.get_json()["code"], "WRITE_INTENT_REQUIRED")
        self.assertEqual((repo_dir / "style_guide.md").read_text(encoding="utf-8"), original)

    def test_flat_replace_text_replaces_unique_span_in_draft_branch(self):
        book_id, repo_dir = self._init_book(book_name="v62_flat_replace_text")
        original = "# Draft\n## 第156章\nNiKo在香蕉道和拱门联动。\n## 第157章\n后文。\n"
        self._write_markdown(repo_dir, "chapter_draft.md", original)
        self._commit_markdown(repo_dir, "chapter_draft.md", "seed chapter draft")
        base_etag = self._read_etag(book_id, "chapter_draft.md")

        resp = self.client.post(
            "/api/draft/replace_text",
            json={
                "book_id": book_id,
                "file_name": "chapter_draft.md",
                "old_text": "NiKo在香蕉道和拱门联动。",
                "new_text": "NiKo在B小和拱门联动。",
                "base_etag": base_etag,
                "origin": "explicit_user_write",
                "message": "fix Mirage callout",
            },
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["match_count"], 1)
        draft_content = self._git_show(repo_dir, "draft/sandbox", "chapter_draft.md")
        self.assertIn("NiKo在B小和拱门联动。", draft_content)
        self.assertNotIn("NiKo在香蕉道", draft_content)
        self.assertEqual(self._git_show(repo_dir, body["mainline_branch"], "chapter_draft.md"), original)

    def test_flat_replace_text_requires_unique_match_or_occurrence(self):
        book_id, repo_dir = self._init_book(book_name="v62_replace_text_unique")
        original = "# Draft\n## A\n重复词。\n## B\n重复词。\n"
        self._write_markdown(repo_dir, "chapter_draft.md", original)
        self._commit_markdown(repo_dir, "chapter_draft.md", "seed repeated text")
        base_etag = self._read_etag(book_id, "chapter_draft.md")

        resp = self.client.post(
            "/api/draft/replace_text",
            json={
                "book_id": book_id,
                "file_name": "chapter_draft.md",
                "old_text": "重复词。",
                "new_text": "替换词。",
                "base_etag": base_etag,
                "origin": "explicit_user_write",
            },
        )

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "TEXT_NOT_UNIQUE")

        resp = self.client.post(
            "/api/draft/replace_text",
            json={
                "book_id": book_id,
                "file_name": "chapter_draft.md",
                "old_text": "重复词。",
                "new_text": "替换词。",
                "occurrence": 2,
                "base_etag": base_etag,
                "origin": "explicit_user_write",
            },
        )

        self.assertEqual(resp.status_code, 200)
        draft_content = self._git_show(repo_dir, "draft/sandbox", "chapter_draft.md")
        self.assertIn("## A\n重复词。\n## B\n替换词。", draft_content)


    def test_chapter_draft_ai_write_loop_guard_blocks_seventh_recent_update(self):
        book_id, repo_dir = self._init_book(book_name="v62_ai_write_loop_guard")
        original = "# Draft\n## A\nseed\n"
        self._write_markdown(repo_dir, "chapter_draft.md", original)

        for index in range(6):
            base_etag = self._read_etag(book_id, "chapter_draft.md")
            resp = self.client.post(
                "/api/draft/replace_markdown_section",
                json={
                    "book_id": book_id,
                    "file_name": "chapter_draft.md",
                    "section_path": ["Draft", "A"],
                    "content": f"## A\nbeat {index}\n",
                    "base_etag": base_etag,
                    "origin": "explicit_user_write",
                    "message": f"loop guard allowed update {index}",
                },
            )
            self.assertEqual(resp.status_code, 200)

        before_block = self._git_show(repo_dir, "draft/sandbox", "chapter_draft.md")
        base_etag = self._read_etag(book_id, "chapter_draft.md")
        resp = self.client.post(
            "/api/draft/replace_markdown_section",
            json={
                "book_id": book_id,
                "file_name": "chapter_draft.md",
                "section_path": ["Draft", "A"],
                "content": "## A\nshould be blocked\n",
                "base_etag": base_etag,
                "origin": "explicit_user_write",
                "message": "loop guard blocked update",
            },
        )

        self.assertEqual(resp.status_code, 429)
        body = resp.get_json()
        self.assertEqual(body["code"], "AI_WRITE_LOOP_GUARD")
        self.assertIn("refusing another draft write", body["message"])
        self.assertEqual(self._git_show(repo_dir, "draft/sandbox", "chapter_draft.md"), before_block)


if __name__ == "__main__":
    unittest.main()
