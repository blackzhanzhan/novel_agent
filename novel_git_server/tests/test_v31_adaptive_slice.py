import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


DELIMITER = "|||CHAPTER_START|||"


class V31AdaptiveSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v31_adaptive_slice_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adaptive_slice_returns_expected_core_structure(self):
        arg1 = [
            f"{DELIMITER}第1章\n正文1",
            f"{DELIMITER}第2章\n正文2",
        ]
        resp = self.client.post("/tools/adaptive_slice", json={"arg1": arg1})
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertEqual(body["total_chapters"], 2)
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["range"], "CH1-2")
        self.assertEqual(body["data"][0]["chapters"][0]["title"], "第1章")
        self.assertEqual(body["data"][0]["chapters"][1]["title"], "第2章")

    def test_adaptive_slice_truncates_long_body_at_300k(self):
        long_body = "a" * 300010
        arg1 = f"{DELIMITER}超长章\n{long_body}"

        resp = self.client.post("/tools/adaptive_slice", json={"arg1": arg1})
        self.assertEqual(resp.status_code, 200)

        chapter = resp.get_json()["data"][0]["chapters"][0]
        self.assertTrue(chapter["content"].endswith("...(Truncated)"))
        self.assertEqual(len(chapter["content"]), 300000 + len("...(Truncated)"))

    def test_adaptive_slice_keeps_batch_count_within_25(self):
        chapters = [f"第{i}章\n正文{i}" for i in range(1, 252)]
        arg1 = DELIMITER.join(chapters)

        resp = self.client.post("/tools/adaptive_slice", json={"arg1": arg1})
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertEqual(body["total_chapters"], 251)
        self.assertLessEqual(len(body["data"]), 25)
        self.assertEqual(body["data"][0]["range"], "CH1-11")
        self.assertEqual(body["data"][-1]["range"], "CH243-251")


if __name__ == "__main__":
    unittest.main()
