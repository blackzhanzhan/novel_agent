import json
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from pipelines import world_model_init as pipeline  # noqa: E402


WORLD_MODEL_MARKDOWN = """# World Model

## 读者承诺与主轴
- **承诺**：测试用世界模型。

## 冲突发动机
- **冲突**：测试冲突。

## 硬约束
- **硬约束**：测试硬约束。

## 软假设
- **软假设**：测试软假设。

## 未回收承诺
- **承诺**：测试承诺。

## 矛盾与风险
- **风险**：测试风险。

## 下游工作流接口
- **接口**：测试接口。
"""


SUMMARY_MARKDOWN = """# Summary

## Batch Archive: CH1-3

### 故事阶段
- 林七夜进入精神病院主线的早期铺垫阶段。

## Batch Archive: CH4-6

### 故事阶段
- 林七夜完成守夜人身份相关的真相揭示，队伍进入高压追杀阶段。

### 核心驱动进度
- 当前核心驱动是追查阿撒托斯污染源，并确认精神病院病人的真实身份。

### 线索状态
- 门之钥线索仍未落地，需要后续回收。
- 精神病院病人身份与神明残响仍有空白。

### 伏笔台账
- 炽天使神墟代价尚未完全说明。
- 倪克斯的恢复程度仍需验证。

### 未兑现承诺
- 阿撒托斯污染源必须给出正面答案。
- 倪克斯与林七夜的关系债需要回收。
- 门之钥线索需要进入主线解释。

### 关系变化
- 林七夜与守夜人小队形成更强协作，但主角仍承担核心风险。

### 本段约束增量
- 后续续写必须保持精神病院与外部神秘事件双线推进。
"""


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self):
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return _FakeResponse(WORLD_MODEL_MARKDOWN)


class WorldModelInitPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"world_model_init_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

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
        ).stdout.strip()

    def _init_book_repo(self, name: str = "book") -> Path:
        repo_dir = self.temp_dir / name
        repo_dir.mkdir(parents=True)
        self._git(repo_dir, "init")
        self._git(repo_dir, "config", "user.email", "tests@example.invalid")
        self._git(repo_dir, "config", "user.name", "Tests")
        (repo_dir / "metadata.json").write_text(
            json.dumps({"book_name": "我在精神病院学斩神"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (repo_dir / "summary.md").write_text(SUMMARY_MARKDOWN, encoding="utf-8")
        self._git(repo_dir, "add", "metadata.json", "summary.md")
        self._git(repo_dir, "commit", "-m", "init book")
        return repo_dir

    def _assert_required_status_fields(self, content: str) -> None:
        for field in pipeline.STATUS_CARD_REQUIRED_FIELDS:
            match = re.search(rf"{re.escape(field)}\s*[：:]\s*(.+)", content)
            self.assertIsNotNone(match, f"{field} missing")
            self.assertTrue(match.group(1).strip(), f"{field} has a blank value")

    def test_status_card_builder_fills_required_fields_without_blank_values(self):
        repo_dir = self._init_book_repo()
        shallow_summary = repo_dir / "summary.md"
        shallow_summary.write_text("## Batch Archive: CH1-1\n### 故事阶段\n", encoding="utf-8")

        content = pipeline._build_status_card(str(repo_dir), str(shallow_summary))

        self._assert_required_status_fields(content)
        self.assertIn("当前节奏阶段：待确认", content)
        self.assertIn("未兑现承诺 Top3：1. 待确认；2. 待确认；3. 待确认", content)

    def test_status_card_driver_focus_skips_category_only_markdown_labels(self):
        repo_dir = self._init_book_repo()
        (repo_dir / "summary.md").write_text(
            """# Summary

## Batch Archive: CH2015-2021

### 故事阶段
- 终局之战：林七夜在梦境循环中与阿撒托斯进行最终对决。

### 核心驱动进度
**升级/战斗类：**
- 境界/战力: 林七夜成为高维世界主宰，等同阿撒托斯级。
**轮回/循环/无限类：**
- 循环状态: 最终循环已终结。

### 未兑现承诺
- 林七夜送纪念回家 (CH2021, 对纪念) — 已兑现。
""",
            encoding="utf-8",
        )

        content = pipeline._build_status_card(str(repo_dir), str(repo_dir / "summary.md"))

        self._assert_required_status_fields(content)
        self.assertIn("当前驱动焦点：境界/战力: 林七夜成为高维世界主宰，等同阿撒托斯级。", content)
        self.assertIn("驱动依据：境界/战力: 林七夜成为高维世界主宰，等同阿撒托斯级。", content)
        self.assertNotIn("当前驱动焦点：*升级/战斗类：**", content)
        self.assertNotIn("驱动依据：*升级/战斗类：**", content)

    def test_extraction_and_verify_prompts_require_constraint_lifecycle(self):
        for prompt in (pipeline.EXTRACTION_PROMPT, pipeline.VERIFY_PROMPT):
            self.assertIn("CONSTRAINT_LIFECYCLE_PROTOCOL", prompt)
            self.assertIn("current-active", prompt)
            self.assertIn("historical-only", prompt)
            self.assertIn("disabled-in-current-scope", prompt)
            self.assertIn("Constraint Lifecycle Ledger", prompt)

    def test_insert_constraint_lifecycle_ledger_marks_legacy_constraints(self):
        content = pipeline._insert_constraint_lifecycle_ledger(WORLD_MODEL_MARKDOWN)

        self.assertIn("### Constraint Lifecycle Ledger", content)
        self.assertIn("legacy-unclassified", content)
        self.assertIn("current-active", content)
        self.assertIn("historical-only", content)
        self.assertIn("disabled-in-current-scope", content)
        self.assertLess(
            content.index("### Constraint Lifecycle Ledger"),
            content.index(f"## {pipeline.REQUIRED_SECTIONS[3]}"),
        )

    def test_insert_constraint_lifecycle_ledger_is_idempotent(self):
        once = pipeline._insert_constraint_lifecycle_ledger(WORLD_MODEL_MARKDOWN)
        twice = pipeline._insert_constraint_lifecycle_ledger(once)

        self.assertEqual(once, twice)
        self.assertEqual(twice.count("### Constraint Lifecycle Ledger"), 1)

    def test_fresh_pipeline_commits_world_model_and_status_card_together(self):
        repo_dir = self._init_book_repo()
        fake_llm = _FakeLLM()

        with patch.object(pipeline, "_build_llm", return_value=fake_llm):
            result = pipeline.run_pipeline("book", str(repo_dir), str(repo_dir / "summary.md"))

        self.assertEqual(result["failed_batches"], [])
        self.assertEqual(fake_llm.calls, 2)
        changed = set(self._git(repo_dir, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertIn("world_model.md", changed)
        self.assertIn("status_card.md", changed)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        status_card = (repo_dir / "status_card.md").read_text(encoding="utf-8")
        self._assert_required_status_fields(status_card)
        self.assertIn("阿撒托斯污染源必须给出正面答案", status_card)

    def test_pipeline_inserts_constraint_lifecycle_ledger_into_world_model(self):
        repo_dir = self._init_book_repo()

        with patch.object(pipeline, "_build_llm", return_value=_FakeLLM()):
            result = pipeline.run_pipeline("book", str(repo_dir), str(repo_dir / "summary.md"))

        self.assertEqual(result["failed_batches"], [])
        world_model = (repo_dir / "world_model.md").read_text(encoding="utf-8")
        self.assertIn("### Constraint Lifecycle Ledger", world_model)
        self.assertIn("legacy-unclassified", world_model)
        self.assertIn("disabled-in-current-scope", world_model)

    def test_verified_extraction_skip_repairs_shallow_status_card_without_llm(self):
        repo_dir = self._init_book_repo()
        (repo_dir / "world_model.md").write_text(WORLD_MODEL_MARKDOWN, encoding="utf-8")
        (repo_dir / "status_card.md").write_text(
            "# 状态卡片\n\n## 当前时间线\n\n- 当前地点：\n",
            encoding="utf-8",
        )
        self._git(repo_dir, "add", "world_model.md", "status_card.md")
        self._git(repo_dir, "commit", "-m", "batch init: verified full extraction")

        with patch.object(pipeline, "_build_llm", side_effect=AssertionError("LLM should not run")):
            result = pipeline.run_pipeline("book", str(repo_dir), str(repo_dir / "summary.md"))

        self.assertTrue(result["skipped"])
        self.assertEqual(result["failed_batches"], [])
        self.assertEqual(self._git(repo_dir, "log", "-1", "--pretty=%s"), pipeline.STATUS_CARD_REPAIR_COMMIT_MESSAGE)
        changed = set(self._git(repo_dir, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(changed, {"status_card.md"})
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        status_card = (repo_dir / "status_card.md").read_text(encoding="utf-8")
        self._assert_required_status_fields(status_card)

    def test_force_rebuild_bypasses_verified_extraction_skip_and_runs_llm(self):
        repo_dir = self._init_book_repo()
        (repo_dir / "world_model.md").write_text(WORLD_MODEL_MARKDOWN, encoding="utf-8")
        (repo_dir / "status_card.md").write_text(
            "# 鐘舵€佸崱鐗嘰n\n## 褰撳墠鏃堕棿绾縗n\n- 褰撳墠鍦扮偣锛歕n",
            encoding="utf-8",
        )
        self._git(repo_dir, "add", "world_model.md", "status_card.md")
        self._git(repo_dir, "commit", "-m", "batch init: verified full extraction")

        fake_llm = _FakeLLM()
        with patch.object(pipeline, "_build_llm", return_value=fake_llm):
            result = pipeline.run_pipeline(
                "book",
                str(repo_dir),
                str(repo_dir / "summary.md"),
                force_rebuild=True,
            )

        self.assertFalse(result.get("skipped", False))
        self.assertTrue(result["force_rebuild"])
        self.assertEqual(result["failed_batches"], [])
        self.assertEqual(fake_llm.calls, 2)
        self.assertEqual(self._git(repo_dir, "log", "-1", "--pretty=%s"), "batch init: verified full extraction")
        changed = set(self._git(repo_dir, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertIn("world_model.md", changed)
        self.assertIn("status_card.md", changed)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

    def test_init_batch_route_passes_force_rebuild_to_pipeline(self):
        app = gs.create_app(storage_root=str(self.temp_dir))
        app.testing = True
        client = app.test_client()
        init_resp = client.post("/books/init", json={"book_name": "force_route_case"})
        self.assertEqual(init_resp.status_code, 200)
        book_id = init_resp.get_json()["book_id"]
        repo_dir = self.temp_dir / book_id
        (repo_dir / "summary.md").write_text(SUMMARY_MARKDOWN, encoding="utf-8")

        captured: dict[str, object] = {}

        def fake_run_pipeline(**kwargs):
            captured.update(kwargs)
            sse_queue = kwargs.get("sse_queue")
            if sse_queue is not None:
                sse_queue.put(
                    {
                        "event": "done",
                        "data": {"completed": 0, "failed": 0, "force_rebuild": kwargs.get("force_rebuild")},
                    }
                )
            return {"completed_batches": [], "failed_batches": [], "force_rebuild": kwargs.get("force_rebuild")}

        with patch("pipelines.world_model_init.run_pipeline", side_effect=fake_run_pipeline):
            resp = client.post(
                "/api/world/init_batch_pipeline",
                json={"book_id": book_id, "force_rebuild": True},
                buffered=True,
            )
            body = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(captured["force_rebuild"])
        self.assertEqual(captured["book_id"], book_id)
        self.assertEqual(str(captured["book_dir"]), str(repo_dir))
        self.assertIn('"force_rebuild": true', body)

    def test_verified_extraction_skip_repairs_malformed_status_card_value_without_llm(self):
        repo_dir = self._init_book_repo()
        (repo_dir / "world_model.md").write_text(WORLD_MODEL_MARKDOWN, encoding="utf-8")
        (repo_dir / "status_card.md").write_text(
            "\n".join(
                [
                    "# 状态卡片",
                    "",
                    "- 当前节奏阶段：终局之战",
                    "- 张力等级：高",
                    "- 上次满足点位置及类型：CH2015-2021：真相揭示",
                    "- 建议下个满足点距离：1-2章内",
                    "- 当前驱动焦点：*升级/战斗类：**",
                    "- 读者预期方向：待确认",
                    "- 主角状态：待确认",
                    "- 未兑现承诺 Top3：1. 待确认；2. 待确认；3. 待确认",
                    "- 伏笔压力：高",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self._git(repo_dir, "add", "world_model.md", "status_card.md")
        self._git(repo_dir, "commit", "-m", "batch init: verified full extraction")

        with patch.object(pipeline, "_build_llm", side_effect=AssertionError("LLM should not run")):
            result = pipeline.run_pipeline("book", str(repo_dir), str(repo_dir / "summary.md"))

        self.assertTrue(result["skipped"])
        self.assertEqual(result["failed_batches"], [])
        self.assertEqual(self._git(repo_dir, "log", "-1", "--pretty=%s"), pipeline.STATUS_CARD_REPAIR_COMMIT_MESSAGE)

        status_card = (repo_dir / "status_card.md").read_text(encoding="utf-8")
        self._assert_required_status_fields(status_card)
        self.assertIn("当前驱动焦点：当前核心驱动是追查阿撒托斯污染源", status_card)
        self.assertNotIn("*升级/战斗类：**", status_card)


if __name__ == "__main__":
    unittest.main()
