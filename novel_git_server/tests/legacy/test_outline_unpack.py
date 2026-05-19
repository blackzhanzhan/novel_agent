import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class OutlineProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = ROOT_DIR / ".tmp_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = temp_root / f"outline_protocol_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        gs.DATA_DIR = self.temp_dir / "data"
        gs.DB_PATH = gs.DATA_DIR / "database.json"
        gs.OUTLINES_DIR = gs.DATA_DIR / "outlines"
        gs.SNAPSHOT_TEMPLATE_PATH = gs.DATA_DIR / "snapshot_template.md"
        gs.init_db()
        gs.app.testing = True
        self.client = gs.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_outline_json_hard_cut(self):
        plain_resp = self.client.post(
            "/save_outline",
            data=b"raw text",
            content_type="text/plain; charset=utf-8",
        )
        self.assertEqual(plain_resp.status_code, 400)
        self.assertEqual(plain_resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_save_outline_action_mismatch_and_missing_field(self):
        mismatch_resp = self.client.post(
            "/save_outline",
            json={"action": "commit", "content": "outline"},
        )
        self.assertEqual(mismatch_resp.status_code, 400)
        self.assertEqual(mismatch_resp.get_json()["code"], "ACTION_MISMATCH")

        missing_resp = self.client.post(
            "/save_outline",
            json={"action": "save_outline"},
        )
        self.assertEqual(missing_resp.status_code, 400)
        self.assertEqual(missing_resp.get_json()["code"], "MISSING_FIELD")

    def test_save_outline_rewrap_and_filename_priority(self):
        content = """---
title: fake
message: fake message
---
# 鏉ヨ嚜姝ｆ枃棣栬鐨勬爣棰?杩欓噷鏄鏂囧唴瀹?"""
        payload = {
            "action": "save_outline",
            "title": "鏉ヨ嚜JSON鏍囬",
            "message": "real message",
            "parent_id": "p123",
            "content": content,
        }
        resp = self.client.post("/save_outline", json=payload)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()

        db = json.loads(gs.DB_PATH.read_text(encoding="utf-8"))
        latest = db["outlines"][-1]

        self.assertEqual(latest["title"], "鏉ヨ嚜JSON鏍囬")
        self.assertIn('message: "real message"', latest["raw_content"])
        self.assertIn('parent_id: "p123"', latest["raw_content"])
        self.assertNotIn("fake message", latest["raw_content"])
        self.assertNotIn("title: fake", latest["raw_content"])
        self.assertIn("杩欓噷鏄鏂囧唴瀹?, latest["content"])

        file_path = ROOT_DIR / body["file_path"]
        self.assertTrue(file_path.exists())
        self.assertIn("鏉ヨ嚜JSON鏍囬", file_path.name)

    def test_save_outline_title_fallback_to_content(self):
        payload = {
            "action": "save_outline",
            "message": "fallback title",
            "content": "# 绗竴琛岃嚜鍔ㄦ爣棰榎n姝ｆ枃鍐呭",
        }
        resp = self.client.post("/save_outline", json=payload)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        db = json.loads(gs.DB_PATH.read_text(encoding="utf-8"))
        latest = db["outlines"][-1]
        self.assertEqual(latest["title"], "绗竴琛岃嚜鍔ㄦ爣棰?)
        self.assertIn("绗竴琛岃嚜鍔ㄦ爣棰?, body["file_path"])

    def test_outlines_latest_full_query(self):
        p1 = {
            "action": "save_outline",
            "title": "澶х翰涓€",
            "message": "o1",
            "content": "绗竴鏉″墽鎯?,
        }
        p2 = {
            "action": "save_outline",
            "title": "澶х翰浜?,
            "message": "o2",
            "content": "绗簩鏉″墽鎯咃紙鐩爣锛?,
        }
        self.assertEqual(self.client.post("/save_outline", json=p1).status_code, 200)
        self.assertEqual(self.client.post("/save_outline", json=p2).status_code, 200)

        resp = self.client.get("/outlines?latest=1&full=1")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["latest"]["title"], "澶х翰浜?)
        self.assertIn("绗簩鏉″墽鎯咃紙鐩爣锛?, body["latest"]["content"])
        self.assertIn("metadata", body["latest"])


if __name__ == "__main__":
    unittest.main()

