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
from agents import world_draft  # noqa: E402

try:
    import git  # noqa: F401

    GITPYTHON_AVAILABLE = True
except Exception:
    GITPYTHON_AVAILABLE = False


@unittest.skipUnless(GITPYTHON_AVAILABLE, "GitPython not installed")
class V44WorldDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v44_world_draft_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _git(self, repo_dir: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc.stdout.strip()

    def _bootstrap_book(self, *, book_name: str) -> tuple[str, Path]:
        resp = self.client.get(
            "/books/get_file",
            query_string={"book_name": book_name, "file_name": "world_model.md"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        return body["book_id"], self.temp_dir / body["book_id"]

    def test_sync_creates_draft_branch_and_returns_latest_commit(self):
        book_name = "草稿分支同步"
        resp = self.client.post(
            "/api/world/sync",
            json={
                "book_name": book_name,
                "content": "# human-v1",
                "mock_ai_markdown": "# ai-v1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        self.assertEqual(body["status"], "success")
        self.assertEqual(body["branch"], "draft/sandbox")
        self.assertEqual(body["content"], "# ai-v1")
        self.assertTrue(body["commit_id"])
        self.assertIn("warning", body)

        repo_dir = self.temp_dir / body["book_id"]
        branches = self._git(repo_dir, "branch", "--list")
        self.assertIn("draft/sandbox", branches)
        active_branch = self._git(repo_dir, "branch", "--show-current")
        self.assertEqual(active_branch, "draft/sandbox")

        world_model = (repo_dir / "world_model.md").read_text(encoding="utf-8")
        self.assertEqual(world_model, "# ai-v1")

    def test_rollback_resets_draft_branch_to_target_commit(self):
        book_name = "草稿分支回滚"
        first = self.client.post(
            "/api/world/sync",
            json={
                "book_name": book_name,
                "content": "# human-v1",
                "mock_ai_markdown": "# ai-v1",
            },
        )
        self.assertEqual(first.status_code, 200)
        first_body = first.get_json()

        second = self.client.post(
            "/api/world/sync",
            json={
                "book_name": book_name,
                "content": "# human-v2",
                "mock_ai_markdown": "# ai-v2",
            },
        )
        self.assertEqual(second.status_code, 200)
        book_id = second.get_json()["book_id"]

        rollback = self.client.post(
            "/api/world/rollback",
            json={
                "book_id": book_id,
                "commit_hash": first_body["commit_id"],
            },
        )
        self.assertEqual(rollback.status_code, 200)
        body = rollback.get_json()
        self.assertEqual(body["branch"], "draft/sandbox")
        self.assertEqual(body["commit_id"], first_body["commit_id"])
        self.assertEqual(body["content"], "# ai-v1")
        self.assertIn("warning", body)

        repo_dir = self.temp_dir / book_id
        self.assertEqual(self._git(repo_dir, "rev-parse", "HEAD"), first_body["commit_id"])
        self.assertEqual((repo_dir / "world_model.md").read_text(encoding="utf-8"), "# ai-v1")

    def test_confirm_merges_draft_into_mainline_and_deletes_draft(self):
        book_name = "草稿分支确认"
        sync = self.client.post(
            "/api/world/sync",
            json={
                "book_name": book_name,
                "content": "# human-confirm",
                "mock_ai_markdown": "# ai-confirm",
            },
        )
        self.assertEqual(sync.status_code, 200)
        book_id = sync.get_json()["book_id"]

        confirm = self.client.post("/api/world/confirm", json={"book_id": book_id})
        self.assertEqual(confirm.status_code, 200)
        body = confirm.get_json()

        repo_dir = self.temp_dir / book_id
        self.assertIn(body["mainline_branch"], {"main", "master"})
        self.assertEqual(self._git(repo_dir, "branch", "--show-current"), body["mainline_branch"])
        self.assertNotIn("draft/sandbox", self._git(repo_dir, "branch", "--list"))
        self.assertEqual((repo_dir / "world_model.md").read_text(encoding="utf-8"), "# ai-confirm")
        self.assertIn("warning", body)

    def test_confirm_uses_current_non_default_branch_as_mainline(self):
        book_name = "草稿分支主线切换"
        book_id, repo_dir = self._bootstrap_book(book_name=book_name)

        self._git(repo_dir, "config", "user.email", "v44-mainline@local")
        self._git(repo_dir, "config", "user.name", "V44 Mainline")
        self._git(repo_dir, "add", "--all")
        self._git(repo_dir, "commit", "-m", "seed mainline commit")
        self._git(repo_dir, "checkout", "-b", "feature/timeline_a")

        sync = self.client.post(
            "/api/world/sync",
            json={
                "book_id": book_id,
                "content": "# human-feature",
                "mock_ai_markdown": "# ai-feature",
            },
        )
        self.assertEqual(sync.status_code, 200)

        confirm = self.client.post("/api/world/confirm", json={"book_id": book_id})
        self.assertEqual(confirm.status_code, 200)
        body = confirm.get_json()

        self.assertEqual(body["mainline_branch"], "feature/timeline_a")
        self.assertEqual(self._git(repo_dir, "branch", "--show-current"), "feature/timeline_a")
        self.assertEqual((repo_dir / "world_model.md").read_text(encoding="utf-8"), "# ai-feature")

    def test_review_diff_preview_uses_mainline_baseline_when_draft_is_new(self):
        init = self.client.post("/books/init", json={"book_name": "v44_review_preview_mainline"})
        self.assertEqual(init.status_code, 200)
        repo_dir = self.temp_dir / init.get_json()["book_id"]

        self._git(repo_dir, "config", "user.email", "v44-preview@local")
        self._git(repo_dir, "config", "user.name", "V44 Preview")
        (repo_dir / "world_model.md").write_text("# world\n\n## section\nold\n", encoding="utf-8")
        self._git(repo_dir, "add", "world_model.md")
        self._git(repo_dir, "commit", "-m", "seed world")
        self._git(repo_dir, "checkout", "-b", "draft/sandbox")
        (repo_dir / "world_model.md").write_text("# world\n\n## section\nold\n\n### probe\nnew\n", encoding="utf-8")
        self._git(repo_dir, "add", "world_model.md")
        self._git(repo_dir, "commit", "-m", "draft probe")

        preview = world_draft._build_review_diff_preview(
            str(repo_dir),
            "world_model.md",
            (repo_dir / "world_model.md").read_text(encoding="utf-8"),
        )

        self.assertIn("+### probe", preview)
        self.assertNotIn("@@ -0,0", preview)


if __name__ == "__main__":
    unittest.main()
