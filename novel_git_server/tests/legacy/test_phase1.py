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


def make_snapshot(chapter_name: str, body_text: str, hp: int = 100, foreshadow: str = "鏆傛棤") -> str:
    return f"""# 灏忚鐘舵€佸揩鐓?## 鏍稿績鐘舵€佹。妗?### 浜虹墿鍗?- 涓昏HP: {hp}
- 涓昏鐘舵€? 绋冲畾

## 寰呭洖鏀朵紡绗?- {foreshadow}

## 绔犺妭姊楁
- {chapter_name}

## 鍔ㄦ€佹枃椋庢寚鍗?- 鑺傚绱у噾

## 閿欒妗ｆ
- 绂佸繉瑙勫垯: 璁惧畾涓嶆紓绉?
## 鏈€鏂版鏂?{body_text}
"""


class Phase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = ROOT_DIR / ".tmp_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = temp_root / f"phase1_{uuid.uuid4().hex}"
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

    def _post_commit(self, markdown_body: str, message: str, parent_id: str | None = None) -> str:
        payload = {"action": "commit", "message": message, "content": markdown_body}
        if parent_id:
            payload["parent_id"] = parent_id
        response = self.client.post("/commit", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["commit_id"]

    def test_11_commit_as_full_snapshot(self):
        snapshot_a = make_snapshot("绗?绔犲ぇ绾?, "蹇収A姝ｆ枃", hp=98, foreshadow="鎬€琛ㄧ嚎绱?)
        snapshot_b = make_snapshot("绗?绔犲ぇ绾?, "蹇収B姝ｆ枃", hp=92, foreshadow="榛戝競鍦板浘")

        commit_a = self._post_commit(snapshot_a, "snapshot A")
        commit_b = self._post_commit(snapshot_b, "snapshot B")

        latest = self.client.get("/checkout").get_json()["payload"]["markdown"]
        old = self.client.get(f"/checkout?commit_id={commit_a}").get_json()["payload"]["markdown"]
        self.assertIn("蹇収B姝ｆ枃", latest)
        self.assertIn("蹇収A姝ｆ枃", old)

        db = json.loads(gs.DB_PATH.read_text(encoding="utf-8"))
        self.assertEqual(db["commits"][commit_b]["parent_id"], commit_a)

    def test_12_view_pruning_infrastructure(self):
        commit = self._post_commit(
            make_snapshot("绗?绔?, "姝ｆ枃1", hp=97, foreshadow="閾舵垝鎸?),
            "init",
        )

        full_resp = self.client.get("/checkout")
        full_text = full_resp.get_json()["payload"]["markdown"]
        self.assertIn("鍔ㄦ€佹枃椋庢寚鍗?, full_text)
        self.assertEqual(full_resp.status_code, 200)

        bad_resp = self.client.get("/checkout?view=invalid_view")
        self.assertEqual(bad_resp.status_code, 400)
        self.assertEqual(self.client.get("/checkout").get_json()["payload"]["commit_id"], commit)

    def test_13_view_world_model(self):
        commit_a = self._post_commit(
            make_snapshot("涓栫晫鎺ㄨ繘", "姝ｆ枃A", hp=100, foreshadow="鏃х嚎绱?),
            "world baseline",
        )

        world_model_update = """## 鏍稿績鐘舵€佹。妗?### 浜虹墿鍗?- 涓昏HP: 77
- 涓昏鐘舵€? 楂樺帇
"""
        update_resp = self.client.post(
            "/world_model",
            json={
                "action": "update_world_model",
                "message": "wm update",
                "content": world_model_update,
                "parent_id": commit_a,
            },
        )
        self.assertEqual(update_resp.status_code, 200, update_resp.get_data(as_text=True))
        commit_b = update_resp.get_json()["commit_id"]

        world_model_latest = self.client.get("/checkout?view=world_model").get_json()["payload"]["markdown"]
        world_model_old = self.client.get(
            f"/checkout?view=world_model&commit_id={commit_a}"
        ).get_json()["payload"]["markdown"]
        self.assertIn("涓昏HP: 77", world_model_latest)
        self.assertIn("涓昏HP: 100", world_model_old)

        latest_full = self.client.get("/checkout").get_json()["payload"]["markdown"]
        self.assertIn("涓昏HP: 77", latest_full)
        db = json.loads(gs.DB_PATH.read_text(encoding="utf-8"))
        self.assertEqual(db["commits"][commit_b]["parent_id"], commit_a)

    def test_14_view_writer(self):
        self._post_commit(make_snapshot("绗?绔犲ぇ绾?, "绗?绔犳鏂?, hp=100), "chapter1")
        self._post_commit(make_snapshot("绗?绔犲ぇ绾?, "绗?绔犳鏂?, hp=95), "chapter2")
        self._post_commit(make_snapshot("绗?绔犲ぇ绾?, "绗?绔犳鏂?, hp=93), "chapter3")

        writer_view = self.client.get("/checkout?view=writer").get_json()["payload"]["markdown"]
        self.assertIn("鍔ㄦ€佹枃椋庢寚鍗?, writer_view)
        self.assertIn("绗?绔犳鏂?, writer_view)
        self.assertIn("绗?绔犳鏂?, writer_view)
        self.assertIn("绗?绔犲ぇ绾?, writer_view)
        self.assertNotIn("绗?绔犳鏂?, writer_view)

    def test_15_view_reviewer(self):
        self._post_commit(
            make_snapshot("绗?绔犲ぇ绾?, "绗?绔犲緟瀹℃鏂?, hp=88, foreshadow="瀵嗗鏆楅棬"),
            "reviewer test",
        )
        reviewer_view = self.client.get("/checkout?view=reviewer").get_json()["payload"]["markdown"]
        self.assertIn("鏈€鏂版鏂?, reviewer_view)
        self.assertIn("鏍稿績鐘舵€佹。妗?, reviewer_view)
        self.assertIn("閿欒妗ｆ", reviewer_view)
        self.assertNotIn("绔犺妭姊楁", reviewer_view)
        self.assertNotIn("寰呭洖鏀朵紡绗?, reviewer_view)

    def test_16_history_endpoint(self):
        c1 = self._post_commit(make_snapshot("C1", "姝ｆ枃C1"), "msg1")
        c2 = self._post_commit(make_snapshot("C2", "姝ｆ枃C2"), "msg2")
        c3 = self._post_commit(make_snapshot("C3", "姝ｆ枃C3"), "msg3")

        history_resp = self.client.get("/history")
        self.assertEqual(history_resp.status_code, 200)
        body = history_resp.get_json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["history"][0]["commit_id"], c3)
        self.assertEqual(body["history"][1]["commit_id"], c2)
        self.assertEqual(body["history"][2]["commit_id"], c1)
        self.assertEqual(
            set(body["history"][0].keys()),
            {"commit_id", "parent_id", "message", "timestamp"},
        )

    def test_17_snapshot_template(self):
        data = self.client.get("/checkout").get_json()["payload"]["markdown"]
        self.assertTrue(gs.SNAPSHOT_TEMPLATE_PATH.exists())
        self.assertIn("## 鏍稿績鐘舵€佹。妗?, data)
        self.assertIn("## 寰呭洖鏀朵紡绗?, data)
        self.assertIn("## 绔犺妭姊楁", data)
        self.assertIn("## 鍔ㄦ€佹枃椋庢寚鍗?, data)
        self.assertIn("## 閿欒妗ｆ", data)
        self.assertIn("## 鏈€鏂版鏂?, data)

    def test_18_data_flow_loop(self):
        outline_payload = {
            "action": "save_outline",
            "title": "闂幆娴嬭瘯澶х翰",
            "message": "init outline",
            "content": "绗?绔犲埌绗?绔犳帹杩?,
        }
        outline_resp = self.client.post("/save_outline", json=outline_payload)
        self.assertEqual(outline_resp.status_code, 200, outline_resp.get_data(as_text=True))
        self.assertIn("outline_id", outline_resp.get_json())

        initial_snapshot = make_snapshot("鍒濆澶х翰", "鍒濆姝ｆ枃", hp=100, foreshadow="鏃х収鐗?)
        commit0 = self._post_commit(initial_snapshot, "commit0")
        checkout0 = self.client.get("/checkout").get_json()["payload"]["markdown"]
        self.assertIn("鍒濆姝ｆ枃", checkout0)

        wm_resp = self.client.post(
            "/world_model",
            json={
                "action": "update_world_model",
                "message": "wm refine",
                "content": "## 鏍稿績鐘舵€佹。妗圽n- 涓栫晫娉曞垯锛氫唬浠蜂氦鎹?,
                "parent_id": commit0,
            },
        )
        self.assertEqual(wm_resp.status_code, 200, wm_resp.get_data(as_text=True))

        evolved_snapshot = make_snapshot("鎺ㄦ紨鍚庡ぇ绾?, "鎺ㄦ紨鍚庢鏂?, hp=87, foreshadow="鏃х収鐗囧凡鍥炴敹")
        commit1 = self._post_commit(evolved_snapshot, "commit1")

        latest = self.client.get("/checkout").get_json()["payload"]["markdown"]
        rollback = self.client.get(f"/checkout?commit_id={commit0}").get_json()["payload"]["markdown"]
        world_model = self.client.get("/checkout?view=world_model").get_json()["payload"]["markdown"]
        history = self.client.get("/history").get_json()

        self.assertIn("鎺ㄦ紨鍚庢鏂?, latest)
        self.assertIn("鍒濆姝ｆ枃", rollback)
        self.assertIn("鏍稿績鐘舵€佹。妗?, world_model)

        chain_ok = False
        for row in history["history"]:
            if row["commit_id"] == commit1 and row["parent_id"]:
                chain_ok = True
                break
        self.assertTrue(chain_ok)

    def test_19_protocol_hard_cut_and_rewrap(self):
        plain_resp = self.client.post(
            "/commit",
            data=b"raw plain text",
            content_type="text/plain; charset=utf-8",
        )
        self.assertEqual(plain_resp.status_code, 400)
        self.assertEqual(plain_resp.get_json()["code"], "INVALID_PAYLOAD")

        content_with_bad_header = """---
message: hacked
parent_id: bad
---
# 灏忚鐘舵€佸揩鐓?## 鏍稿績鐘舵€佹。妗?- 涓昏HP: 66
"""
        commit_id = self._post_commit(content_with_bad_header, "trusted message")
        db = json.loads(gs.DB_PATH.read_text(encoding="utf-8"))
        stored = db["commits"][commit_id]
        self.assertIn("message: trusted message", stored["raw_payload"])
        self.assertNotIn("message: hacked", stored["raw_payload"])


if __name__ == "__main__":
    unittest.main()

