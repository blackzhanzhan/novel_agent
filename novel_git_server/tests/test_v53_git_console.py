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


class V53GitConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v53_git_console_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _bootstrap_book(self, *, book_name: str) -> tuple[str, Path]:
        resp = self.client.get(
            "/books/get_file",
            query_string={"book_name": book_name, "file_name": "world_model.md"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        book_id = body["book_id"]
        return book_id, self.temp_dir / book_id

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

    def test_status_branch_create_checkout_and_dirty_guard(self):
        book_name = "v53_branch_guard"
        _, repo_dir = self._bootstrap_book(book_name=book_name)

        status_resp = self.client.get("/books/git_status", query_string={"book_name": book_name})
        self.assertEqual(status_resp.status_code, 200)
        status_body = status_resp.get_json()
        self.assertFalse(status_body["is_dirty"])
        mainline_branch = status_body["mainline_branch"]

        create_resp = self.client.post(
            "/books/git_branch_create",
            json={
                "book_name": book_name,
                "branch_name": "feature/branch_guard",
                "from_ref": status_body["head_commit"],
                "checkout": True,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        create_body = create_resp.get_json()
        self.assertEqual(create_body["current_branch"], "feature/branch_guard")

        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nbranch-guard\n", encoding="utf-8")

        dirty_checkout = self.client.post(
            "/books/git_checkout",
            json={"book_name": book_name, "branch_name": mainline_branch},
        )
        self.assertEqual(dirty_checkout.status_code, 409)
        self.assertEqual(dirty_checkout.get_json()["code"], "WORKTREE_DIRTY")

        stage_all = self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.assertEqual(stage_all.status_code, 200)

        commit = self.client.post(
            "/books/git_commit",
            json={"book_name": book_name, "message": "commit dirty branch guard change"},
        )
        self.assertEqual(commit.status_code, 200)

        clean_checkout = self.client.post(
            "/books/git_checkout",
            json={"book_name": book_name, "branch_name": mainline_branch},
        )
        self.assertEqual(clean_checkout.status_code, 200)
        self.assertEqual(clean_checkout.get_json()["current_branch"], mainline_branch)

    def test_file_level_stage_unstage_and_diff_view(self):
        book_name = "v53_stage_unstage"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        self.client.get("/books/git_status", query_string={"book_name": book_name})

        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nfile-level delta\n", encoding="utf-8")

        wt_resp = self.client.get("/books/git_working_tree", query_string={"book_name": book_name})
        self.assertEqual(wt_resp.status_code, 200)
        entries = wt_resp.get_json()["entries"]
        world_entry = next((row for row in entries if row["path"] == "world_model.md"), None)
        self.assertIsNotNone(world_entry)
        self.assertTrue(world_entry["unstaged"])

        diff_resp = self.client.get(
            "/books/git_diff_view",
            query_string={"book_name": book_name, "scope": "unstaged", "path": "world_model.md"},
        )
        self.assertEqual(diff_resp.status_code, 200)
        diff_body = diff_resp.get_json()
        self.assertTrue(diff_body["changed"])
        self.assertIn("file-level delta", diff_body["new_text"])

        stage_resp = self.client.post(
            "/books/git_stage",
            json={"book_name": book_name, "path": "world_model.md"},
        )
        self.assertEqual(stage_resp.status_code, 200)
        staged_entry = next((row for row in stage_resp.get_json()["entries"] if row["path"] == "world_model.md"), None)
        self.assertIsNotNone(staged_entry)
        self.assertTrue(staged_entry["staged"])

        unstage_resp = self.client.post(
            "/books/git_unstage",
            json={"book_name": book_name, "path": "world_model.md"},
        )
        self.assertEqual(unstage_resp.status_code, 200)
        unstaged_entry = next((row for row in unstage_resp.get_json()["entries"] if row["path"] == "world_model.md"), None)
        self.assertIsNotNone(unstaged_entry)
        self.assertTrue(unstaged_entry["unstaged"])

    def test_history_commit_files_and_commit_scope_diff(self):
        book_name = "v53_history_commit"
        _, repo_dir = self._bootstrap_book(book_name=book_name)

        # Ensure baseline commit exists before manual mutations.
        status_resp = self.client.get("/books/git_status", query_string={"book_name": book_name})
        self.assertEqual(status_resp.status_code, 200)

        summary_path = repo_dir / "summary.md"
        summary_path.write_text(summary_path.read_text(encoding="utf-8") + "\nsummary change\n", encoding="utf-8")
        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nworld change\n", encoding="utf-8")

        stage_all = self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.assertEqual(stage_all.status_code, 200)

        commit_resp = self.client.post(
            "/books/git_commit",
            json={"book_name": book_name, "message": "history list commit"},
        )
        self.assertEqual(commit_resp.status_code, 200)
        commit_id = commit_resp.get_json()["commit_id"]

        history_resp = self.client.get("/books/git_history_list", query_string={"book_name": book_name, "limit": 20})
        self.assertEqual(history_resp.status_code, 200)
        commits = history_resp.get_json()["commits"]
        self.assertTrue(any(row["commit_id"] == commit_id for row in commits))

        files_resp = self.client.get(
            "/books/git_commit_files",
            query_string={"book_name": book_name, "commit_id": commit_id},
        )
        self.assertEqual(files_resp.status_code, 200)
        files = files_resp.get_json()["files"]
        changed_paths = {row["path"] for row in files}
        self.assertIn("summary.md", changed_paths)
        self.assertIn("world_model.md", changed_paths)

        commit_diff_resp = self.client.get(
            "/books/git_diff_view",
            query_string={
                "book_name": book_name,
                "scope": "commit",
                "commit_id": commit_id,
                "path": "world_model.md",
            },
        )
        self.assertEqual(commit_diff_resp.status_code, 200)
        commit_diff = commit_diff_resp.get_json()
        self.assertTrue(commit_diff["changed"])
        self.assertIn("world change", commit_diff["new_text"])

    def test_hard_rollback_prunes_other_branches(self):
        book_name = "v53_hard_rollback"
        _, repo_dir = self._bootstrap_book(book_name=book_name)

        status_resp = self.client.get("/books/git_status", query_string={"book_name": book_name})
        self.assertEqual(status_resp.status_code, 200)
        head_commit = status_resp.get_json()["head_commit"]

        create_feature = self.client.post(
            "/books/git_branch_create",
            json={
                "book_name": book_name,
                "branch_name": "feature/rollback_target",
                "from_ref": head_commit,
                "checkout": True,
            },
        )
        self.assertEqual(create_feature.status_code, 200)

        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nfirst rollback mark\n", encoding="utf-8")
        stage_all_1 = self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.assertEqual(stage_all_1.status_code, 200)
        first_commit_resp = self.client.post(
            "/books/git_commit",
            json={"book_name": book_name, "message": "rollback checkpoint"},
        )
        self.assertEqual(first_commit_resp.status_code, 200)
        rollback_target = first_commit_resp.get_json()["commit_id"]

        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nsecond rollback mark\n", encoding="utf-8")
        stage_all_2 = self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.assertEqual(stage_all_2.status_code, 200)
        second_commit_resp = self.client.post(
            "/books/git_commit",
            json={"book_name": book_name, "message": "rollback future commit"},
        )
        self.assertEqual(second_commit_resp.status_code, 200)
        self.assertNotEqual(second_commit_resp.get_json()["commit_id"], rollback_target)

        create_side = self.client.post(
            "/books/git_branch_create",
            json={
                "book_name": book_name,
                "branch_name": "feature/side_story",
                "from_ref": rollback_target,
                "checkout": False,
            },
        )
        self.assertEqual(create_side.status_code, 200)

        rollback_resp = self.client.post(
            "/books/git_hard_rollback",
            json={
                "book_name": book_name,
                "target_commit": rollback_target,
                "delete_other_branches": True,
            },
        )
        self.assertEqual(rollback_resp.status_code, 200)
        rollback_body = rollback_resp.get_json()
        self.assertEqual(rollback_body["current_branch"], "feature/rollback_target")
        self.assertEqual(rollback_body["head_commit"], rollback_target)
        self.assertIn("feature/side_story", rollback_body["deleted_branches"])

        branch_list = self._git(repo_dir, "branch", "--format=%(refname:short)")
        branches = {line.strip() for line in branch_list.splitlines() if line.strip()}
        self.assertEqual(branches, {"feature/rollback_target"})

        final_content = world_path.read_text(encoding="utf-8")
        self.assertIn("first rollback mark", final_content)
        self.assertNotIn("second rollback mark", final_content)

    def test_hard_rollback_branch_read_does_not_mutate_head(self):
        book_name = "v53_hard_rollback_branch_read"
        _, repo_dir = self._bootstrap_book(book_name=book_name)

        status_resp = self.client.get("/books/git_status", query_string={"book_name": book_name})
        self.assertEqual(status_resp.status_code, 200)

        # Build a rollback target commit where one layout file is intentionally absent.
        self._git(repo_dir, "rm", "error_archive.md")
        self._git(repo_dir, "commit", "-m", "remove error archive from history")
        rollback_target = self._git(repo_dir, "rev-parse", "HEAD")

        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nfuture mark\n", encoding="utf-8")
        self._git(repo_dir, "add", "--", "world_model.md")
        self._git(repo_dir, "commit", "-m", "future commit after rollback target")
        self.assertNotEqual(self._git(repo_dir, "rev-parse", "HEAD"), rollback_target)

        rollback_resp = self.client.post(
            "/books/git_hard_rollback",
            json={
                "book_name": book_name,
                "target_commit": rollback_target,
                "delete_other_branches": False,
            },
        )
        self.assertEqual(rollback_resp.status_code, 200)
        self.assertEqual(rollback_resp.get_json()["head_commit"], rollback_target)

        branches_resp = self.client.get("/books/git_branches", query_string={"book_name": book_name})
        self.assertEqual(branches_resp.status_code, 200)

        # Loading branch list must not inject extra bootstrap commits after rollback.
        self.assertEqual(self._git(repo_dir, "rev-parse", "HEAD"), rollback_target)

    def test_git_path_guard_allows_dot_git_prefix_files_but_blocks_git_dir(self):
        book_name = "v53_git_path_guard"
        _, repo_dir = self._bootstrap_book(book_name=book_name)

        (repo_dir / ".gitattributes").write_text("*.md text eol=lf\n", encoding="utf-8")
        (repo_dir / ".gitmodules").write_text("[submodule \"demo\"]\n\tpath = demo\n", encoding="utf-8")
        workflows_dir = repo_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        (workflows_dir / "ci.yml").write_text("name: ci\n", encoding="utf-8")

        allowed_paths = [
            ".gitignore",
            ".gitattributes",
            ".gitmodules",
            ".github/workflows/ci.yml",
        ]
        for rel_path in allowed_paths:
            resp = self.client.get(
                "/books/git_file_view",
                query_string={"book_name": book_name, "path": rel_path},
            )
            self.assertEqual(resp.status_code, 200, rel_path)

        denied_paths = [
            ".git",
            ".git/config",
            "frontend/.git/config",
            "frontend\\.git\\config",
        ]
        for rel_path in denied_paths:
            resp = self.client.get(
                "/books/git_file_view",
                query_string={"book_name": book_name, "path": rel_path},
            )
            self.assertEqual(resp.status_code, 400, rel_path)
            self.assertEqual(resp.get_json()["code"], "INVALID_PATH")

    # ── git_merge tests ─────────────────────────────────────────────────────────

    def test_git_merge_fast_forward(self):
        """Merging a feature branch into master via fast-forward advances HEAD."""
        book_name = "v53_merge_ff"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        status = self.client.get("/books/git_status", query_string={"book_name": book_name}).get_json()
        head = status["head_commit"]
        mainline = status["mainline_branch"]

        # Create and populate feature branch
        self.client.post(
            "/books/git_branch_create",
            json={"book_name": book_name, "branch_name": "feature/ff", "from_ref": head, "checkout": True},
        )
        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nff-marker\n", encoding="utf-8")
        self.client.post("/books/git_stage_all", json={"book_name": book_name})
        feature_commit = self.client.post(
            "/books/git_commit", json={"book_name": book_name, "message": "ff feature commit"}
        ).get_json()["commit_id"]

        # Switch back to mainline, then merge
        self.client.post("/books/git_checkout", json={"book_name": book_name, "branch_name": mainline})

        resp = self.client.post(
            "/books/git_merge",
            json={"book_name": book_name, "source_branch": "feature/ff"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["merge_type"], "fast_forward")
        self.assertEqual(body["commit_id"], feature_commit,
                         "HEAD should equal the feature tip on fast-forward")

    def test_git_merge_no_ff_no_hang(self):
        """--no-ff without explicit message must inject a default and return promptly."""
        import time
        book_name = "v53_merge_no_ff"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        status = self.client.get("/books/git_status", query_string={"book_name": book_name}).get_json()
        head = status["head_commit"]
        mainline = status["mainline_branch"]

        self.client.post(
            "/books/git_branch_create",
            json={"book_name": book_name, "branch_name": "feature/noff", "from_ref": head, "checkout": True},
        )
        world_path = repo_dir / "world_model.md"
        world_path.write_text(world_path.read_text(encoding="utf-8") + "\nnoff-marker\n", encoding="utf-8")
        self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.client.post("/books/git_commit", json={"book_name": book_name, "message": "noff feature"})

        self.client.post("/books/git_checkout", json={"book_name": book_name, "branch_name": mainline})

        t0 = time.monotonic()
        resp = self.client.post(
            "/books/git_merge",
            json={"book_name": book_name, "source_branch": "feature/noff", "no_ff": True},
        )
        elapsed = time.monotonic() - t0

        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["merge_type"], "merge_commit",
                         "--no-ff must always produce a merge commit")
        self.assertLess(elapsed, 5.0,
                        "merge --no-ff must return within 5 s (no editor hang)")
        # Verify the injected default message is present in commit log
        log = self._git(repo_dir, "log", "-1", "--format=%s")
        self.assertIn("feature/noff", log, "default merge message should name source branch")

    def test_git_merge_conflict_aborted_with_file_list(self):
        """Conflict must return MERGE_CONFLICT 409 with conflicted_files and clean worktree."""
        book_name = "v53_merge_conflict"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        status = self.client.get("/books/git_status", query_string={"book_name": book_name}).get_json()
        head = status["head_commit"]
        mainline = status["mainline_branch"]

        # Branch A: append line A to world_model.md
        self.client.post(
            "/books/git_branch_create",
            json={"book_name": book_name, "branch_name": "feature/conflict-a", "from_ref": head, "checkout": True},
        )
        world_path = repo_dir / "world_model.md"
        world_path.write_text("line-A-only\n", encoding="utf-8")
        self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.client.post("/books/git_commit", json={"book_name": book_name, "message": "branch A change"})

        # Branch B starting from same base: append line B
        self.client.post("/books/git_checkout", json={"book_name": book_name, "branch_name": mainline})
        self.client.post(
            "/books/git_branch_create",
            json={"book_name": book_name, "branch_name": "feature/conflict-b", "from_ref": head, "checkout": True},
        )
        world_path.write_text("line-B-only\n", encoding="utf-8")
        self.client.post("/books/git_stage_all", json={"book_name": book_name})
        self.client.post("/books/git_commit", json={"book_name": book_name, "message": "branch B change"})

        # Merge branch A into branch B -> conflict
        resp = self.client.post(
            "/books/git_merge",
            json={"book_name": book_name, "source_branch": "feature/conflict-a"},
        )
        self.assertEqual(resp.status_code, 409, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["code"], "MERGE_CONFLICT")
        self.assertIn("conflicted_files", body)
        self.assertTrue(len(body["conflicted_files"]) > 0, "conflicted_files must be non-empty")
        self.assertIn("world_model.md", body["conflicted_files"])

        # Worktree must be clean after abort
        wt = self.client.get("/books/git_working_tree", query_string={"book_name": book_name}).get_json()
        self.assertFalse(wt["is_dirty"], "worktree should be clean after merge abort")

    def test_git_merge_already_up_to_date(self):
        """Merging a branch whose commits are already in current branch -> up_to_date."""
        book_name = "v53_merge_uptd"
        _, repo_dir = self._bootstrap_book(book_name=book_name)
        status = self.client.get("/books/git_status", query_string={"book_name": book_name}).get_json()
        head = status["head_commit"]
        mainline = status["mainline_branch"]

        # Create branch at same commit as mainline (no new commits)
        self.client.post(
            "/books/git_branch_create",
            json={"book_name": book_name, "branch_name": "feature/already-merged",
                  "from_ref": head, "checkout": False},
        )

        resp = self.client.post(
            "/books/git_merge",
            json={"book_name": book_name, "source_branch": "feature/already-merged"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["merge_type"], "up_to_date")


if __name__ == "__main__":
    unittest.main()
