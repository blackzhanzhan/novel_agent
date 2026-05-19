import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from queue import Queue
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from pipelines import style_artifact_init as pipeline  # noqa: E402


def fake_diagnostics(*_args, **_kwargs):
    return {
        "status": "success",
        "source_count": 12,
        "source_files": ["0001.md"],
        "warnings": [],
        "outputs": {
            "style_fingerprint.md": "# Fingerprint\n\n- source-backed rhythm\n",
            "style_review.md": "# Review\n\n- author-facing advice\n",
            "style_constraints_for_continuation.md": "# Constraints\n\n- imitation reference only\n",
        },
    }


class V71StyleInitPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v71_style_init_{uuid.uuid4().hex}"
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
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()

    def _init_book(self, name: str = "v71_style") -> tuple[str, Path]:
        resp = self.client.post("/books/init", json={"book_name": name})
        self.assertEqual(resp.status_code, 200)
        book_id = resp.get_json()["book_id"]
        return book_id, self.temp_dir / book_id

    def test_pipeline_writes_three_style_artifacts_and_leaves_book_repo_clean(self):
        book_id, repo_dir = self._init_book()

        with patch.object(pipeline, "generate_style_diagnostics", side_effect=fake_diagnostics):
            result = pipeline.run_pipeline(book_id=book_id, book_dir=repo_dir, force_rebuild=True)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["failed_artifacts"], [])
        self.assertEqual(set(result["updated_artifacts"]), set(pipeline.STYLE_ARTIFACT_FILES))
        changed = set(self._git(repo_dir, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(changed, set(pipeline.STYLE_ARTIFACT_FILES))
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")
        self.assertIn("source-backed rhythm", (repo_dir / "style_fingerprint.md").read_text(encoding="utf-8"))

    def test_pipeline_skips_existing_non_template_artifacts_without_force(self):
        book_id, repo_dir = self._init_book("v71_style_skip")
        for file_name in pipeline.STYLE_ARTIFACT_FILES:
            (repo_dir / file_name).write_text(f"# {file_name}\n\n- already generated\n", encoding="utf-8")
        self._git(repo_dir, "add", "--", *pipeline.STYLE_ARTIFACT_FILES)
        self._git(repo_dir, "commit", "-m", "seed style artifacts", "--", *pipeline.STYLE_ARTIFACT_FILES)
        head_before = self._git(repo_dir, "rev-parse", "HEAD")

        with patch.object(pipeline, "generate_style_diagnostics", side_effect=AssertionError("should skip")):
            result = pipeline.run_pipeline(book_id=book_id, book_dir=repo_dir, force_rebuild=False)

        self.assertTrue(result["skipped"])
        self.assertEqual(head_before, self._git(repo_dir, "rev-parse", "HEAD"))
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

    def test_pipeline_emits_promptless_progress_events(self):
        book_id, repo_dir = self._init_book("v71_style_events")
        queue: Queue = Queue()

        with patch.object(pipeline, "generate_style_diagnostics", side_effect=fake_diagnostics):
            result = pipeline.run_pipeline(book_id=book_id, book_dir=repo_dir, sse_queue=queue, force_rebuild=True)

        self.assertEqual(result["status"], "success")
        events = []
        while not queue.empty():
            events.append(queue.get()["event"])
        self.assertIn("ack", events)
        self.assertIn("progress", events)
        self.assertIn("done", events)

    def test_style_init_route_rejects_draft_file_path_escape(self):
        book_id, _repo_dir = self._init_book("v71_style_escape")

        resp = self.client.post(
            "/api/style/init_pipeline",
            json={"book_id": book_id, "draft_file": "../chapter_draft.md"},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_style_init_route_streams_done_payload(self):
        book_id, _repo_dir = self._init_book("v71_style_route")

        with patch.object(pipeline, "generate_style_diagnostics", side_effect=fake_diagnostics):
            resp = self.client.post(
                "/api/style/init_pipeline",
                json={"book_id": book_id, "force_rebuild": True},
                buffered=True,
            )
            body = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: ack", body)
        self.assertIn("event: done", body)
        self.assertIn("style_fingerprint.md", body)


if __name__ == "__main__":
    unittest.main()
