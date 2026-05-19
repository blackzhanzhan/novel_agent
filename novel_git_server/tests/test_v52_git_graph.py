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


class V52GitGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v52_git_graph_{uuid.uuid4().hex}"
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
        self.assertIsInstance(body, dict)
        book_id = body["book_id"]
        repo_dir = self.temp_dir / book_id
        return book_id, repo_dir

    def _set_local_identity(self, repo_dir: Path) -> None:
        self._git(repo_dir, "config", "user.email", "git-graph-tests@local")
        self._git(repo_dir, "config", "user.name", "Git Graph Tests")

    def test_git_graph_returns_multi_parent_merge_and_refs(self):
        book_name = "v52_merge_graph"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        self._set_local_identity(repo_dir)
        main_branch = self._git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")

        world_path = repo_dir / "world_model.md"
        world_path.write_text("# seed world\n\nmainline baseline\n", encoding="utf-8")
        self._git(repo_dir, "add", "world_model.md")
        self._git(repo_dir, "commit", "-m", "seed world for graph test")

        self._git(repo_dir, "checkout", "-b", "feature/status_lane")
        status_path = repo_dir / "status_card.md"
        status_path.write_text(status_path.read_text(encoding="utf-8") + "\n- feature_lane: true\n", encoding="utf-8")
        self._git(repo_dir, "add", "status_card.md")
        self._git(repo_dir, "commit", "-m", "feature status update")

        self._git(repo_dir, "checkout", main_branch)
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\n## mainline update\n", encoding="utf-8")
        self._git(repo_dir, "add", "world_model.md")
        self._git(repo_dir, "commit", "-m", "mainline world update")

        self._git(
            repo_dir,
            "merge",
            "--no-ff",
            "feature/status_lane",
            "-m",
            "merge feature status lane",
        )
        merge_commit = self._git(repo_dir, "rev-parse", "HEAD")

        resp = self.client.get("/books/git_graph", query_string={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertGreaterEqual(body["total"], 4)

        commits = body["commits"]
        merge_row = next((row for row in commits if row["commit_id"] == merge_commit), None)
        self.assertIsNotNone(merge_row)
        self.assertEqual(len(merge_row["parent_ids"]), 2)
        self.assertEqual(merge_row["parent_id"], merge_row["parent_ids"][0])
        self.assertIn(main_branch, merge_row["refs"])

    def test_git_graph_fresh_repo_has_structured_commits(self):
        book_name = "v52_fresh_graph"
        self._bootstrap_book(book_name=book_name)

        resp = self.client.get("/books/git_graph", query_string={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertGreaterEqual(body["total"], 1)

        row = body["commits"][0]
        self.assertIn("commit_id", row)
        self.assertIn("parent_ids", row)
        self.assertIsInstance(row["parent_ids"], list)
        self.assertIn("refs", row)
        self.assertIsInstance(row["refs"], list)

    def test_history_keeps_parent_id_and_exposes_parent_ids(self):
        book_name = "v52_history_compat"
        self._bootstrap_book(book_name=book_name)

        resp = self.client.get("/books/history", query_string={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertGreaterEqual(body["total"], 1)
        first = body["history"][0]
        self.assertIn("parent_id", first)
        self.assertIn("parent_ids", first)
        self.assertIsInstance(first["parent_ids"], list)


if __name__ == "__main__":
    unittest.main()
