import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from tools.migrate_v24_to_v30 import migrate_storage  # noqa: E402


class V3MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_storage = tmp_root / f"v3_migration_{uuid.uuid4().hex}"
        self.temp_storage.mkdir(parents=True, exist_ok=True)

        (self.temp_storage / "world_model.md").write_text("legacy world", encoding="utf-8")
        (self.temp_storage / "outlines").mkdir(parents=True, exist_ok=True)
        (self.temp_storage / "outlines" / "outline_old.md").write_text("legacy outline", encoding="utf-8")
        (self.temp_storage / "database.json").write_text('{"legacy": true}', encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_storage, ignore_errors=True)

    def test_migration_moves_data_and_drops_db_dependency(self):
        result = migrate_storage(self.temp_storage, "book_migrate", dry_run=False)

        book_dir = Path(result["book_dir"])
        self.assertTrue((book_dir / "world_model.md").exists())
        self.assertFalse((book_dir / "outlines").exists())
        self.assertFalse((self.temp_storage / "database.json").exists())
        self.assertTrue(Path(result["database_archive"]).exists())
        self.assertTrue(Path(result["outlines_archive"]).exists())
        self.assertTrue(Path(result["outlines_archive"]).joinpath("outline_old.md").exists())

        app = gs.create_app(storage_root=str(self.temp_storage))
        app.testing = True
        client = app.test_client()
        resp = client.get("/checkout?book_id=book_migrate&include=world_model")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("legacy world", resp.get_json()["payload"]["markdown"])


if __name__ == "__main__":
    unittest.main()

