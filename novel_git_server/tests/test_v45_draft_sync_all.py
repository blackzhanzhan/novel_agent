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


class V45DraftSyncAllTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v45_draft_sync_{uuid.uuid4().hex}"
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

    def _get_file(self, *, book_name: str, file_name: str) -> dict:
        resp = self.client.get(
            "/books/get_file",
            query_string={
                "book_name": book_name,
                "file_name": file_name,
            },
        )
        if resp.status_code == 404:
            init_resp = self.client.post("/books/init", json={"book_name": book_name})
            self.assertEqual(init_resp.status_code, 200)
            resp = self.client.get(
                "/books/get_file",
                query_string={
                    "book_name": book_name,
                    "file_name": file_name,
                },
            )
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def test_sync_all_multifile_single_commit_on_draft_branch(self):
        book_name = "v45_multi_success"
        wm = self._get_file(book_name=book_name, file_name="world_model.md")
        sc = self._get_file(book_name=book_name, file_name="status_card.md")

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "write_scope": "world_core",
                "message": "sync all round 1",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# world v45\n\nnew law",
                        "base_etag": wm["etag"],
                    },
                    {
                        "file_name": "status_card.md",
                        "op": "append",
                        "content": "\n\n- HP: 73",
                        "base_etag": sc["etag"],
                    },
                ],
            },
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["branch"], "draft/sandbox")
        self.assertTrue(body["commit_id"])
        self.assertEqual(len(body["updated_files"]), 2)

        repo_dir = self.temp_dir / body["book_id"]
        mainline = body["mainline_branch"]
        self.assertEqual(self._git(repo_dir, "branch", "--show-current"), "draft/sandbox")

        ahead = self._git(repo_dir, "rev-list", "--count", "draft/sandbox", "--not", mainline)
        self.assertEqual(ahead, "1")

        mainline_world = self._git(repo_dir, "show", f"{mainline}:world_model.md")
        self.assertNotIn("# world v45", mainline_world)

    def test_sync_all_rejects_non_world_target_file(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v45_reject_chapter"})
        self.assertEqual(init_resp.status_code, 200)
        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": "v45_reject_chapter",
                "writes": [
                    {
                        "file_name": "chapters/0096_clutch.md",
                        "op": "update",
                        "content": "chapter payload",
                    }
                ],
            },
        )

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "TARGET_PATH_FORBIDDEN")

    def test_sync_all_rejects_non_active_target_in_strict_scope(self):
        book_name = "v45_reject_strict_target"
        wm = self._get_file(book_name=book_name, file_name="world_model.md")
        sc = self._get_file(book_name=book_name, file_name="status_card.md")

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "write_scope": "active_file_strict",
                "active_file": "world_model.md",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# strict world",
                        "base_etag": wm["etag"],
                    },
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": "# strict status",
                        "base_etag": sc["etag"],
                    },
                ],
            },
        )

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["code"], "TARGET_PATH_FORBIDDEN")

    def test_sync_all_conflict_is_atomic_and_no_commit(self):
        book_name = "v45_atomic_conflict"
        wm = self._get_file(book_name=book_name, file_name="world_model.md")
        sc = self._get_file(book_name=book_name, file_name="status_card.md")

        mutate = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "# mutated status",
                "base_etag": sc["etag"],
                "message": "mutate before conflict",
            },
        )
        self.assertEqual(mutate.status_code, 200)

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# should not land",
                        "base_etag": wm["etag"],
                    },
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": "# stale update",
                        "base_etag": sc["etag"],
                    },
                ],
            },
        )

        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["code"], "WRITE_CONFLICT")
        self.assertIn("draft_file", body)

        latest_world = self._get_file(book_name=book_name, file_name="world_model.md")
        self.assertEqual(latest_world["content"], wm["content"])

        repo_dir = self.temp_dir / latest_world["book_id"]
        branches = self._git(repo_dir, "branch", "--list")
        if "draft/sandbox" in branches:
            ahead = self._git(repo_dir, "rev-list", "--count", "draft/sandbox", "--not", "master")
            self.assertEqual(ahead, "0")

    def test_sync_all_conflict_keeps_draft_file_in_strict_scope(self):
        book_name = "v45_strict_conflict"
        sc = self._get_file(book_name=book_name, file_name="status_card.md")

        mutate = self.client.post(
            "/books/update_file",
            json={
                "book_name": book_name,
                "file_name": "status_card.md",
                "content": "# strict mutated",
                "base_etag": sc["etag"],
                "message": "mutate for strict conflict",
            },
        )
        self.assertEqual(mutate.status_code, 200)

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "write_scope": "active_file_strict",
                "active_file": "status_card.md",
                "writes": [
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": "# stale strict payload",
                        "base_etag": sc["etag"],
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["code"], "WRITE_CONFLICT")
        self.assertIn("draft_file", body)

    def test_sync_all_auto_repairs_untracked_planning_files(self):
        init_resp = self.client.post("/books/init", json={"book_name": "v45_untracked_planning"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        repo_dir = self.temp_dir / book_id

        self._git(
            repo_dir,
            "rm",
            "--cached",
            "--quiet",
            "--",
            "brainstorm.md",
            "master_outline.md",
            "arc_outline.md",
            "chapter_outline.md",
        )
        self._git(repo_dir, "commit", "-m", "simulate legacy untracked planning files")

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_id": book_id,
                "write_scope": "active_file_strict",
                "active_file": "brainstorm.md",
                "writes": [
                    {
                        "file_name": "brainstorm.md",
                        "op": "update",
                        "content": "# repaired brainstorm\n\nfresh draft",
                    }
                ],
            },
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["commit_id"])
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

    def test_sync_all_auto_truncates_status_card_overflow(self):
        """status_card.md超出20行时，后端自动截断而非拒绝（LLM无法可靠遵守行数约束，由工程层兜底）"""
        book_name = "v45_status_overflow"
        sc = self._get_file(book_name=book_name, file_name="status_card.md")
        overflow_payload = "\n".join([f"- key_{i}: value_{i}" for i in range(1, 22)])  # 21 lines

        resp = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "write_scope": "active_file_strict",
                "active_file": "status_card.md",
                "writes": [
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": overflow_payload,
                        "base_etag": sc["etag"],
                    }
                ],
            },
        )

        self.assertEqual(resp.status_code, 200, "should succeed with auto-truncation")
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertIn("warning", body, "response must contain truncation warning")
        self.assertIn("truncated", body["warning"])
        updated = {f["file_name"]: f for f in body["updated_files"]}
        self.assertIn("status_card.md", updated)
        self.assertTrue(updated["status_card.md"].get("truncated"), "entry must carry truncated=True")

    def test_draft_rollback_and_confirm_flow(self):
        book_name = "v45_confirm_rollback"
        wm0 = self._get_file(book_name=book_name, file_name="world_model.md")
        sc0 = self._get_file(book_name=book_name, file_name="status_card.md")

        first = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "message": "round-1",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# round1",
                        "base_etag": wm0["etag"],
                    },
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": "# status-round1\n- progress: round1",
                        "base_etag": sc0["etag"],
                    },
                ],
            },
        )
        self.assertEqual(first.status_code, 200)
        first_body = first.get_json()

        wm1 = self._get_file(book_name=book_name, file_name="world_model.md")
        sc1 = self._get_file(book_name=book_name, file_name="status_card.md")

        second = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_id": first_body["book_id"],
                "message": "round-2",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# round2",
                        "base_etag": wm1["etag"],
                    },
                    {
                        "file_name": "status_card.md",
                        "op": "update",
                        "content": "# status-round2\n- progress: round2",
                        "base_etag": sc1["etag"],
                    },
                ],
            },
        )
        self.assertEqual(second.status_code, 200)

        rollback = self.client.post(
            "/api/draft/rollback",
            json={
                "book_id": first_body["book_id"],
                "commit_hash": first_body["commit_id"],
            },
        )
        self.assertEqual(rollback.status_code, 200)
        self.assertEqual(rollback.get_json()["commit_id"], first_body["commit_id"])

        confirm = self.client.post("/api/draft/confirm", json={"book_id": first_body["book_id"]})
        self.assertEqual(confirm.status_code, 200)
        confirm_body = confirm.get_json()
        self.assertTrue(confirm_body.get("draft_branch_deleted"))

        repo_dir = self.temp_dir / first_body["book_id"]
        self.assertNotIn("draft/sandbox", self._git(repo_dir, "branch", "--list"))
        mainline = confirm_body["mainline_branch"]

        mainline_world = self._git(repo_dir, "show", f"{mainline}:world_model.md")
        self.assertIn("# round1", mainline_world)
        self.assertNotIn("# round2", mainline_world)

    def test_confirm_materializes_accepted_chapter_draft_into_chapter_files(self):
        book_name = "v45_confirm_chapter_canon"
        init_resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        draft_markdown = (
            "# 续写草稿\n\n"
            "## 第153章 伊甸园的枪\n"
            "正文153\n\n"
            "## 第154章 影子\n"
            "正文154\n\n"
            "## 第155章 Veto桌上的神\n"
            "正文155\n"
        )

        sync = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_id": book_id,
                "active_file": "chapter_draft.md",
                "write_scope": "active_file_strict",
                "message": "write rolling chapters 153-155",
                "writes": [
                    {
                        "file_name": "chapter_draft.md",
                        "op": "update",
                        "content": draft_markdown,
                    }
                ],
            },
        )
        self.assertEqual(sync.status_code, 200)

        confirm = self.client.post("/api/draft/confirm", json={"book_id": book_id})

        self.assertEqual(confirm.status_code, 200)
        body = confirm.get_json()
        self.assertTrue(body.get("draft_branch_deleted"))
        self.assertTrue(body.get("chapter_canon_commit_id"))
        self.assertTrue(body.get("chapter_draft_reset_commit_id"))
        self.assertEqual([item["number"] for item in body["materialized_chapters"]], [153, 154, 155])
        self.assertEqual({item["status"] for item in body["materialized_chapters"]}, {"created"})
        self.assertEqual(
            [(item["action"], item["agent_key"]) for item in body["post_confirm_actions"]],
            [("distill_status_card", "world_model"), ("consider_world_model_update", "world_model")],
        )
        post_confirm_payload = body["post_confirm_payload"]
        self.assertEqual(post_confirm_payload["route_agent_key"], "world_model")
        self.assertEqual(post_confirm_payload["active_file"], "status_card.md")
        self.assertEqual(post_confirm_payload["write_scope"], "world_core")
        self.assertEqual(post_confirm_payload["required_writes"], ["status_card.md"])
        self.assertEqual(post_confirm_payload["optional_writes"], ["world_model.md", "domain_rules.md"])
        self.assertIn("chapter_draft.md", post_confirm_payload["forbidden_writes"])
        self.assertTrue(post_confirm_payload["no_prose_boundary"]["world_model_route_must_not_rewrite_prose"])
        self.assertTrue(post_confirm_payload["no_prose_boundary"]["review_agent_is_not_responsible"])
        self.assertFalse(post_confirm_payload["no_prose_boundary"]["payload_contains_chapter_prose"])
        payload_text = repr(post_confirm_payload)
        self.assertIn("chapters/0153_第153章_伊甸园的枪.md", payload_text)
        self.assertNotIn("正文153", payload_text)
        self.assertNotIn("正文154", payload_text)
        self.assertNotIn("正文155", payload_text)

        repo_dir = self.temp_dir / book_id
        mainline = body["mainline_branch"]
        archived_153 = self._git(repo_dir, "show", f"{mainline}:chapters/0153_第153章_伊甸园的枪.md")
        archived_154 = self._git(repo_dir, "show", f"{mainline}:chapters/0154_第154章_影子.md")
        archived_155 = self._git(repo_dir, "show", f"{mainline}:chapters/0155_第155章_Veto桌上的神.md")
        self.assertIn("## 第153章 伊甸园的枪\n正文153", archived_153)
        self.assertIn("## 第154章 影子\n正文154", archived_154)
        self.assertIn("## 第155章 Veto桌上的神\n正文155", archived_155)

        reset_draft = self._git(repo_dir, "show", f"{mainline}:chapter_draft.md")
        self.assertIn("# 续写草稿", reset_draft)
        self.assertNotIn("正文153", reset_draft)
        self.assertNotIn("正文154", reset_draft)
        self.assertNotIn("正文155", reset_draft)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

    def test_confirm_refuses_conflicting_existing_chapter_archive(self):
        book_name = "v45_confirm_chapter_conflict"
        init_resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        repo_dir = self.temp_dir / book_id
        existing_path = repo_dir / "chapters" / "0153_第153章_旧章.md"
        existing_path.write_text("## 第153章 旧章\n既有正文\n", encoding="utf-8")
        self._git(repo_dir, "add", "--", "chapters/0153_第153章_旧章.md")
        self._git(repo_dir, "commit", "-m", "seed existing chapter")

        sync = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_id": book_id,
                "active_file": "chapter_draft.md",
                "write_scope": "active_file_strict",
                "message": "write conflicting chapter",
                "writes": [
                    {
                        "file_name": "chapter_draft.md",
                        "op": "update",
                        "content": "# 续写草稿\n\n## 第153章 新章\n新的正文\n",
                    }
                ],
            },
        )
        self.assertEqual(sync.status_code, 200)

        confirm = self.client.post("/api/draft/confirm", json={"book_id": book_id})

        self.assertEqual(confirm.status_code, 409)
        body = confirm.get_json()
        self.assertEqual(body["code"], "CHAPTER_CANON_CONFLICT")
        self.assertEqual(self._git(repo_dir, "branch", "--show-current"), "master")
        self.assertIn("draft/sandbox", self._git(repo_dir, "branch", "--list", "draft/sandbox"))
        self.assertIn("既有正文", existing_path.read_text(encoding="utf-8"))

    def test_confirm_without_chapter_draft_change_keeps_empty_materialization(self):
        book_name = "v45_confirm_no_chapter_canon"
        wm0 = self._get_file(book_name=book_name, file_name="world_model.md")
        sync = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "message": "world only",
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# world only",
                        "base_etag": wm0["etag"],
                    }
                ],
            },
        )
        self.assertEqual(sync.status_code, 200)

        confirm = self.client.post("/api/draft/confirm", json={"book_id": sync.get_json()["book_id"]})

        self.assertEqual(confirm.status_code, 200)
        body = confirm.get_json()
        self.assertEqual(body["materialized_chapters"], [])
        self.assertEqual(body["chapter_canon_commit_id"], "")
        self.assertEqual(body["chapter_draft_reset_commit_id"], "")
        self.assertEqual(body["post_confirm_actions"], [])
        self.assertIsNone(body["post_confirm_payload"])

    def test_draft_rollback_requires_commit_hash(self):
        book_name = "v45_rollback_requires_hash"
        wm = self._get_file(book_name=book_name, file_name="world_model.md")
        sync = self.client.post(
            "/api/draft/sync_all",
            json={
                "book_name": book_name,
                "writes": [
                    {
                        "file_name": "world_model.md",
                        "op": "update",
                        "content": "# draft-for-rollback",
                        "base_etag": wm["etag"],
                    }
                ],
            },
        )
        self.assertEqual(sync.status_code, 200)
        book_id = sync.get_json()["book_id"]

        rollback = self.client.post(
            "/api/draft/rollback",
            json={
                "book_id": book_id,
            },
        )
        self.assertEqual(rollback.status_code, 400)
        self.assertEqual(rollback.get_json()["code"], "MISSING_FIELD")


if __name__ == "__main__":
    unittest.main()
