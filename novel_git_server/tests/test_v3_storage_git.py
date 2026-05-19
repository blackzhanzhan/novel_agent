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


class V3StorageGitTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v3_storage_git_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_repo_auto_init_and_real_hash(self):
        book_id = "book_git"
        r1 = self.client.post(
            "/commit_world_state",
            json={"book_id": book_id, "content": "state v1", "message": "first"},
        )
        self.assertEqual(r1.status_code, 200)
        body1 = r1.get_json()
        self.assertTrue(body1["commit_id"])

        repo_dir = self.temp_dir / book_id
        self.assertTrue((repo_dir / ".git").is_dir())
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        self.assertEqual(body1["commit_id"], head)

        r2 = self.client.post(
            "/commit_world_state",
            json={"book_id": book_id, "content": "state v1", "message": "second"},
        )
        self.assertEqual(r2.status_code, 200)
        body2 = r2.get_json()
        self.assertTrue(body2["commit_id"])
        head2 = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        self.assertEqual(body2["commit_id"], head2)


if __name__ == "__main__":
    unittest.main()

