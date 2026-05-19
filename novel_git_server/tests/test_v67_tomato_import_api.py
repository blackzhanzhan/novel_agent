import json
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
from agents.tomato_import import (  # noqa: E402
    _compose_layered_archive_summary,
    _find_missing_chapters,
    _get_chapter_titles,
    _normalize_summary,
    _patch_summary,
    _trigger_summary_generation,
)
from utils.session_runtime import resolve_dev_repo_root  # noqa: E402


class V67TomatoImportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v67_tomato_import_api_{uuid.uuid4().hex}"
        self.storage_root = self.temp_dir / "storage"
        self.source_root = self.temp_dir / "tomato_source"
        self.source_dir = self.source_root / "测试小说"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self._write_source()
        self.app = gs.create_app(storage_root=str(self.storage_root))
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
        ).stdout.strip()

    def _chapter_body(self, seed: str) -> str:
        return "\n\n".join(
            [
                f"　　{seed}第一段保留网页阅读时的自然缩进和空行，人物行动、环境线索与对话节奏都在同一段里展开，避免导入后被切成碎片。",
                f"　　{seed}第二段继续补足可读正文长度，让质量门槛能够区分正常章节与下载失败、截断、广告残留或错误切章的坏样本。",
                f"　　{seed}第三段用于验证 Markdown 写入后仍然接近原网页排版，后续读书存档 Agent 可以直接读取这些章节文件。",
                f"　　{seed}第四段模拟番茄小说网页上的连续正文，保留全角缩进、自然断段和稳定标点，给后续章节合并与资料归档留下可复用结构。",
                f"　　{seed}第五段继续拉开章节体量，保证这不是序章、番外或截断片段，而是一段足以通过基础质量门槛的正文样本。",
                f"　　{seed}第六段用于覆盖更接近真实网文章节的长度边界，确保导入报告在普通章节上保持低风险结论。",
            ]
        )

    def _write_source(self) -> None:
        (self.source_dir / "0000_书籍信息.txt").write_text(
            "书名：测试小说\n作者：测试作者\nbook_id=123456\n",
            encoding="utf-8",
        )
        (self.source_dir / "0001_第一章_开局.txt").write_text(
            f"第一章 开局\n\n{self._chapter_body('开局')}\n",
            encoding="utf-8",
        )
        (self.source_dir / "0002_第二章_推进.txt").write_text(
            f"第二章 推进\n\n{self._chapter_body('推进')}\n",
            encoding="utf-8",
        )

    def _online_download_payload(self, target_file: str = "0001_Test.md") -> dict:
        return {
            "book_name": "online reset book",
            "author": "test author",
            "chapter_count": 1,
            "quality": {"can_confirm": True, "risk_level": "ok", "issues": []},
            "chapters": [
                {
                    "target_file": target_file,
                    "markdown": "# Test Chapter\n\nbody",
                }
            ],
        }

    def _write_world_conversation_runtime(self, book_id: str, conversation_id: str = "conv_stale") -> list[Path]:
        agent_dir = resolve_dev_repo_root(None) / "conversations" / "world_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        files = [
            agent_dir / f"{book_id}.index.json",
            agent_dir / f"{book_id}__{conversation_id}.jsonl",
        ]
        files[0].write_text(
            json.dumps(
                {
                    "book_id": book_id,
                    "agent_key": "world_agent",
                    "active_conversation_id": conversation_id,
                    "conversations": [{"conversation_id": conversation_id}],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        files[1].write_text('{"role":"user","text":"old init"}\n', encoding="utf-8")
        for path in files:
            self.addCleanup(lambda p=path: p.unlink(missing_ok=True))
        return files

    def test_preview_is_read_only(self):
        resp = self.client.post(
            "/books/tomato/preview",
            json={
                "source_dir": str(self.source_dir),
                "allowed_root": str(self.source_root),
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["book_name"], "测试小说")
        self.assertEqual(body["report"]["chapter_count"], 2)
        self.assertTrue(body["quality"]["can_confirm"])
        self.assertFalse(self.storage_root.exists())

    def test_confirm_writes_markdown_chapters_and_import_report(self):
        resp = self.client.post(
            "/books/tomato/confirm",
            json={
                "book_id": "tomato_case",
                "source_dir": str(self.source_dir),
                "allowed_root": str(self.source_root),
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["saved_count"], 2)
        self.assertFalse(body["force_used"])
        self.assertTrue(body["commit_id"])

        repo_dir = self.storage_root / "tomato_case"
        self.assertEqual(body["commit_id"], self._git(repo_dir, "rev-parse", "HEAD"))
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        chapters_dir = repo_dir / "chapters"
        chapter_files = sorted(chapters_dir.glob("*.md"))
        self.assertEqual(len(chapter_files), 2)
        first_content = chapter_files[0].read_text(encoding="utf-8")
        self.assertTrue(first_content.startswith("# 第一章 开局\n\n"))
        self.assertIn("　　开局第一段保留网页阅读时的自然缩进和空行", first_content)
        self.assertIn("　　开局第二段继续补足可读正文长度", first_content)

        report = json.loads((repo_dir / "import_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["source"]["kind"], "tomato_bulk_files")
        self.assertEqual(report["report"]["chapter_count"], 2)
        self.assertEqual(report["quality"]["risk_level"], "ok")
        self.assertEqual(len(report["chapters"]), 2)

        cold_read = self.client.get(
            "/books/get_cold_archive_range",
            query_string={
                "book_id": "tomato_case",
                "file_name": body["chapters"][0]["target_file"],
                "start_line": 1,
                "end_line": 8,
            },
        )
        self.assertEqual(cold_read.status_code, 200)
        cold_body = cold_read.get_json()
        self.assertEqual(cold_body["file_name"], f"chapters/{body['chapters'][0]['target_file']}")
        self.assertIn("# 第一章 开局", cold_body["content"])
        self.assertIn("开局第一段保留网页阅读时的自然缩进和空行", cold_body["content"])

    def test_summary_generation_commits_completion_metadata_and_leaves_repo_clean(self):
        resp = self.client.post(
            "/books/tomato/confirm",
            json={
                "book_id": "summary_clean_case",
                "source_dir": str(self.source_dir),
                "allowed_root": str(self.source_root),
            },
        )
        self.assertEqual(resp.status_code, 200)
        repo_dir = self.storage_root / "summary_clean_case"
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        archive_answer = "\n".join(
            [
                "LONGFORM_LAYERED_ARCHIVE_V1",
                "## Batch Archive: CH1-CH2",
                "",
                "## Batch Overview",
                "- two chapter archive summary",
                "",
                "## Batch Index",
                "- CH1 opening state",
                "- CH2 forward state",
            ]
        )

        with (
            patch("utils.dify_client.chat_messages", side_effect=AssertionError("Dify reading archive is retired")),
            patch("pipelines.summary_archive._invoke_langchain", return_value=archive_answer),
        ):
            _trigger_summary_generation(
                str(repo_dir),
                "summary clean book",
                2,
            )

        metadata = json.loads((repo_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["summary_complete"])
        self.assertEqual(metadata["total_chapters"], 2)
        self.assertEqual(metadata["processed_batches"], 1)
        self.assertEqual(self._git(repo_dir, "status", "--short"), "")

        committed_paths = set(
            line
            for line in self._git(repo_dir, "show", "--name-only", "--format=", "HEAD").splitlines()
            if line
        )
        self.assertIn("summary.md", committed_paths)
        self.assertIn("metadata.json", committed_paths)

    def test_manual_trigger_summary_does_not_require_dify_registry(self):
        resp = self.client.post(
            "/books/tomato/confirm",
            json={
                "book_id": "manual_summary_case",
                "source_dir": str(self.source_dir),
                "allowed_root": str(self.source_root),
            },
        )
        self.assertEqual(resp.status_code, 200)

        with patch("agents.tomato_import.threading.Thread") as thread_cls:
            manual = self.client.post("/books/tomato/trigger_summary", json={"book_id": "manual_summary_case"})

        self.assertEqual(manual.status_code, 200)
        body = manual.get_json()
        self.assertEqual(body["status"], "triggered")
        thread_cls.assert_called_once()
        self.assertIsNone(thread_cls.call_args.kwargs["args"][3])

    def test_online_import_fresh_workspace_resets_stale_world_conversation(self):
        book_id = f"online_reset_{uuid.uuid4().hex[:8]}"
        stale_files = self._write_world_conversation_runtime(book_id)
        self.assertTrue(all(path.exists() for path in stale_files))

        with (
            patch("agents.tomato_import._download_online_book", return_value=self._online_download_payload()),
            patch("agents.tomato_import._trigger_summary_generation"),
        ):
            resp = self.client.post("/books/tomato/online_import", json={"book_id": book_id})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["book_id"], book_id)
        for path in stale_files:
            self.assertFalse(path.exists(), f"fresh online import should delete stale conversation: {path}")

    def test_online_import_collision_keeps_conversation_but_overwrite_resets_it(self):
        book_id = f"online_overwrite_{uuid.uuid4().hex[:8]}"
        payload = self._online_download_payload()

        with (
            patch("agents.tomato_import._download_online_book", return_value=payload),
            patch("agents.tomato_import._trigger_summary_generation"),
        ):
            first = self.client.post("/books/tomato/online_import", json={"book_id": book_id})
        self.assertEqual(first.status_code, 200)

        stale_files = self._write_world_conversation_runtime(book_id, "conv_collision")
        with (
            patch("agents.tomato_import._download_online_book", return_value=payload),
            patch("agents.tomato_import._trigger_summary_generation"),
        ):
            collision = self.client.post("/books/tomato/online_import", json={"book_id": book_id})

        self.assertEqual(collision.status_code, 409)
        self.assertEqual(collision.get_json()["code"], "CHAPTER_EXISTS")
        for path in stale_files:
            self.assertTrue(path.exists(), f"collision-blocked import should keep conversation: {path}")

        with (
            patch("agents.tomato_import._download_online_book", return_value=payload),
            patch("agents.tomato_import._trigger_summary_generation"),
        ):
            overwrite = self.client.post("/books/tomato/online_import", json={"book_id": book_id, "overwrite": True})

        self.assertEqual(overwrite.status_code, 200)
        for path in stale_files:
            self.assertFalse(path.exists(), f"overwrite online import should delete stale conversation: {path}")

    def test_confirm_refuses_collision_without_overwrite(self):
        payload = {
            "book_id": "collision_case",
            "source_dir": str(self.source_dir),
            "allowed_root": str(self.source_root),
        }
        first = self.client.post("/books/tomato/confirm", json=payload)
        self.assertEqual(first.status_code, 200)

        second = self.client.post("/books/tomato/confirm", json=payload)
        self.assertEqual(second.status_code, 409)
        body = second.get_json()
        self.assertEqual(body["code"], "CHAPTER_EXISTS")
        self.assertEqual(len(body["collisions"]), 2)

    def test_confirm_blocks_quality_risk_unless_forced(self):
        bad_source = self.source_root / "重复章节"
        bad_source.mkdir(parents=True, exist_ok=True)
        duplicate_body = self._chapter_body("重复")
        (bad_source / "0001_第一章_复制.txt").write_text(
            f"第一章 复制\n\n{duplicate_body}\n",
            encoding="utf-8",
        )
        (bad_source / "0002_第二章_复制.txt").write_text(
            f"第二章 复制\n\n{duplicate_body}\n",
            encoding="utf-8",
        )

        payload = {
            "book_id": "quality_case",
            "source_dir": str(bad_source),
            "allowed_root": str(self.source_root),
        }
        blocked = self.client.post("/books/tomato/confirm", json=payload)
        self.assertEqual(blocked.status_code, 422)
        blocked_body = blocked.get_json()
        self.assertEqual(blocked_body["code"], "QUALITY_GATE_BLOCKED")
        codes = {issue["code"] for issue in blocked_body["quality"]["issues"]}
        self.assertIn("DUPLICATE_CHAPTER_CONTENT", codes)
        self.assertFalse((self.storage_root / "quality_case").exists())

        forced = self.client.post("/books/tomato/confirm", json={**payload, "force": True})
        self.assertEqual(forced.status_code, 200)
        forced_body = forced.get_json()
        self.assertTrue(forced_body["force_used"])
        self.assertEqual(forced_body["quality"]["risk_level"], "block")

    def test_summary_retry_helpers_match_imported_chapter_filenames(self):
        resp = self.client.post(
            "/books/tomato/confirm",
            json={
                "book_id": "summary_case",
                "source_dir": str(self.source_dir),
                "allowed_root": str(self.source_root),
            },
        )
        self.assertEqual(resp.status_code, 200)

        repo_dir = self.storage_root / "summary_case"
        chapter_titles = _get_chapter_titles(str(repo_dir))

        self.assertEqual(chapter_titles[1], "第一章 开局")
        self.assertEqual(chapter_titles[2], "第二章 推进")

        raw_summary = "==== 摘要 ====\n# 第一章 开局正文粘在标题后\n\n# 第二章 推进\n"
        normalized = _normalize_summary(raw_summary, chapter_titles)

        self.assertNotIn("====", normalized)
        self.assertIn("# 第一章 开局\n\n简述：正文粘在标题后", normalized)
        self.assertEqual(_find_missing_chapters(normalized, chapter_titles), [2])

        patch = _normalize_summary("# 第二章 推进补齐正文", chapter_titles)
        patched = _patch_summary(normalized, patch, chapter_titles)

        self.assertIn("# 第二章 推进\n\n简述：补齐正文", patched)
        self.assertEqual(_find_missing_chapters(patched, chapter_titles), [])

    def test_layered_archive_summary_gets_top_overview(self):
        batch_one = """# Batch Archive: CH1-100

## Batch Overview
- Story phase: 李十五入局并确认大爻世界的吃人逻辑。
- Core conflict: 现代灵魂的正常判断对撞修仙秩序。
- Variable changes: 李十五获得第一条可继承身份线索。
- Downstream usage: world_model / continuation / review

## Chapter Records
### 第一章 开局
- Plot facts: 李十五被卷入异常问话。
- Variable changes: 读者承诺转向黑暗修仙反套路。
- Setting increments: 大爻朝与灵气恶化。
- Foreshadowing and open loops: 谁在问话尚未解释。

## Batch Index
- Character state changes: 李十五 -> 被追问者，拥有异常认知。
- World rules and hard constraints: 灵气不是善意资源。
- Foreshadowing ledger: 问话者身份 -> 第一章/未揭示/可作主线钩子。
"""
        batch_two = """# Batch Archive: CH101-200

## Batch Overview
- Story phase: 阵营开始成形，主角进入更高压环境。
- Core conflict: 存活需求对撞宗门规训。
- Variable changes: 主角的资源和敌友关系重新洗牌。
- Downstream usage: outline / review / continuation

## Batch Index
- Character state changes: 宗门长老 -> 从旁观转为压迫源。
- Conflicts and faction map: 宗门、外敌、主角临时同盟互相牵制。
"""
        body = f"{batch_one}\n\n{batch_two}"
        composed = _compose_layered_archive_summary([batch_one, batch_two], body)

        self.assertTrue(composed.startswith("# 全书总汇总（自动索引）"))
        self.assertIn("## \u6bb5\u843d 1\uff1aCH1-100", composed)
        self.assertIn("## \u6bb5\u843d 2\uff1aCH101-200", composed)
        self.assertIn("# 分批阅读档案", composed)
        self.assertLess(composed.index("# 全书总汇总"), composed.index("# 分批阅读档案"))
        self.assertIn("谁在问话尚未解释", composed)


if __name__ == "__main__":
    unittest.main()
