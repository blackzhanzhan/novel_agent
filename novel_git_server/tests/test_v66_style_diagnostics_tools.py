import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402
from utils.style_diagnostics import (  # noqa: E402
    StyleMetrics,
    build_style_gate,
    generate_style_diagnostics,
    metric_for,
)


class V66StyleDiagnosticsToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v66_style_diagnostics_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _init_book(self, *, book_name: str) -> tuple[str, Path]:
        resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        return body["book_id"], self.temp_dir / body["book_id"]

    def _write_chapter(self, repo_dir: Path, index: int, text: str) -> None:
        chapter_path = repo_dir / "chapters" / f"{index:04d}.md"
        chapter_path.write_text(text, encoding="utf-8")

    def test_generate_style_diagnostics_returns_three_markdown_outputs(self):
        book_id, repo_dir = self._init_book(book_name="v66_style_outputs")
        self._write_chapter(
            repo_dir,
            1,
            "## sample\n\nLight falls through the door.\n\nA voice answers.\n",
        )
        (repo_dir / "chapter_draft.md").write_text(
            "A draft paragraph waits in the room.\n\nAnother beat follows.",
            encoding="utf-8",
        )

        resp = self.client.post(
            "/tools/generate_style_diagnostics",
            json={"book_id": book_id, "source_count": 1},
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        outputs = body["outputs"]
        self.assertIn("style_fingerprint.md", outputs)
        self.assertIn("style_review.md", outputs)
        self.assertIn("style_constraints_for_continuation.md", outputs)
        constraints = outputs["style_constraints_for_continuation.md"]
        self.assertIn("## 当前基准快照", constraints)
        self.assertIn("## 作者视图基准 JSON", constraints)
        self.assertIn('"avg_sentence"', constraints)
        self.assertIn("句式呼吸", constraints)
        self.assertIn("段落节拍", constraints)
        self.assertIn("对白推进度", constraints)
        self.assertIn("## 数值边界", constraints)
        self.assertIn("## 写作硬约束", constraints)
        self.assertIn("## 作者视图基准 JSON", outputs["style_review.md"])
        self.assertIn("style_gate", body)
        self.assertIn(body["style_gate"]["status"], {"pass", "fail"})

    def test_generate_style_diagnostics_rejects_path_escape(self):
        book_id, _repo_dir = self._init_book(book_name="v66_style_escape")

        resp = self.client.post(
            "/tools/generate_style_diagnostics",
            json={"book_id": book_id, "draft_file": "../chapter_draft.md"},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_style_diagnostics_handles_missing_chapters_without_500(self):
        _book_id, repo_dir = self._init_book(book_name="v66_style_empty")

        result = generate_style_diagnostics(book_dir=repo_dir, source_count=3, draft_file="missing.md")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["warnings"])
        self.assertIn("style_constraints_for_continuation.md", result["outputs"])
        self.assertIn("暂无原文基准", result["outputs"]["style_constraints_for_continuation.md"])

    def test_style_gate_marks_obvious_style_drift_as_failure(self):
        _book_id, repo_dir = self._init_book(book_name="v66_style_gate")
        self._write_chapter(
            repo_dir,
            1,
            (
                "## sample\n\n"
                "Light falls through the door.\n\n"
                "A voice answers from the corridor.\n\n"
                "The hand stops on the handle.\n\n"
                "A final signal remains open.\n"
            ),
        )
        drift_block = (
            "because rules process plan data analysis result explanation structure "
            "because rules process plan data analysis result explanation structure "
        )
        (repo_dir / "chapter_draft.md").write_text(drift_block * 18, encoding="utf-8")

        result = generate_style_diagnostics(book_dir=repo_dir, source_count=1)

        self.assertEqual(result["style_gate"]["status"], "fail")
        self.assertFalse(result["style_gate"]["overall_pass"])
        draft_gate = result["style_gate"]["drafts"][0]
        self.assertGreaterEqual(draft_gate["fail_count"], 1)
        failed_metrics = {
            item["metric"]
            for item in draft_gate["items"]
            if item["severity"] == "fail"
        }
        self.assertIn("avg_para", failed_metrics)
        self.assertEqual(draft_gate["repair_plan"]["status"], "required")
        self.assertEqual(draft_gate["repair_plan"]["rewrite_scope"], "current_chapter_only")
        self.assertEqual(draft_gate["repair_plan"]["gate_profile"]["name"], "standard_continuation")
        self.assertEqual(draft_gate["gate_profile"]["name"], "standard_continuation")
        self.assertIn("preserve_outline_facts", draft_gate["repair_plan"]["rewrite_constraints"])
        priority_metrics = {
            item["metric"]: item
            for item in draft_gate["repair_plan"]["priority_metrics"]
        }
        self.assertIn("avg_para", priority_metrics)
        self.assertIn(priority_metrics["avg_para"]["direction"], {"increase", "decrease"})
        self.assertTrue(priority_metrics["avg_para"]["actions"])
        red_flag = draft_gate["red_flags"][0]
        self.assertIn("repair_recipe", red_flag)
        self.assertIn("actions", red_flag["repair_recipe"])
        self.assertIn("current_chapter_only", red_flag["repair_recipe"]["constraints"])

    def test_style_gate_opening_profile_prioritizes_rhythm_without_passing_drift(self):
        baseline = metric_for(
            "Light falls through the door.\n\nA voice answers.\n\nThe hand stops.\n\nOne signal remains.",
            "baseline sample",
        )
        drift = metric_for(
            (
                "because rules process plan data analysis result explanation structure "
                "because rules process plan data analysis result explanation structure "
            )
            * 18,
            "chapter 1 draft",
        )

        gate = build_style_gate([baseline, drift])

        self.assertEqual(gate["status"], "fail")
        draft_gate = gate["drafts"][0]
        self.assertEqual(draft_gate["repair_plan"]["gate_profile"]["name"], "opening_continuation")
        self.assertEqual(
            draft_gate["repair_plan"]["gate_profile"]["target_mode"],
            "rhythm_first_scene_execution",
        )
        self.assertEqual(draft_gate["repair_plan"]["priority_metrics"][0]["metric"], "avg_para")
        self.assertIn("hard_band", draft_gate["repair_plan"]["priority_metrics"][0])
        self.assertTrue(draft_gate["repair_plan"]["metric_couplings"])
        coupling = draft_gate["repair_plan"]["metric_couplings"][0]
        self.assertEqual(coupling["metrics"], ["avg_para", "avg_sentence"])
        self.assertEqual(coupling["joint_revalidation"], ["avg_para", "avg_sentence"])
        self.assertIn("split_trigger", coupling)
        self.assertIn("merge_trigger", coupling)

    def test_style_gate_standard_profile_does_not_emit_opening_couplings(self):
        baseline = metric_for(
            "Light falls through the door.\n\nA voice answers.\n\nThe hand stops.\n\nOne signal remains.",
            "baseline sample",
        )
        drift = metric_for(
            (
                "because rules process plan data analysis result explanation structure "
                "because rules process plan data analysis result explanation structure "
            )
            * 18,
            "chapter 2 draft",
        )

        gate = build_style_gate([baseline, drift])

        draft_gate = gate["drafts"][0]
        self.assertEqual(draft_gate["repair_plan"]["gate_profile"]["name"], "standard_continuation")
        self.assertEqual(draft_gate["repair_plan"].get("metric_couplings"), [])

    def test_bridge_outline_evidence_selects_bridge_profile(self):
        _book_id, repo_dir = self._init_book(book_name="v66_bridge_profile")
        self._write_chapter(
            repo_dir,
            1,
            "## sample\n\nLight falls.\n\nA voice answers.\n\nThe hand stops.\n",
        )
        (repo_dir / "chapter_outline.md").write_text(
            """# 逐章大纲

## 章节卡 4：改写与反噬

- chapter_goal：第一次尝试改写记录，但引发因果连锁，代价由同伴承受
- entry_scene：追兵逼近，主角决定改写一次追踪记录
- conflict_or_obstacle：因果为了让改写合理，必须寻找替罪羊
- payoff：同伴转移锁定标记后被反噬重伤，主角意识到改写不是免费的
- state_change：主角从积极使用权柄转为谨慎使用权柄，必须考虑因果代价
- foreshadowing_action：眉心出现星光印记
- ending_hook：第七页线索出现
- constraint_refs：改写因果代价机制为 WORLD_MODEL_REQUIRED
- evidence_mode：AUTHOR_PROPOSAL
""",
            encoding="utf-8",
        )
        (repo_dir / "chapter_draft.md").write_text(
            "## 第4章 改写与反噬\n\n" + "因为规则解释意味着代价。" * 20,
            encoding="utf-8",
        )

        result = generate_style_diagnostics(book_dir=repo_dir, source_count=1, draft_chapters="4")

        draft_gate = result["style_gate"]["drafts"][0]
        profile = draft_gate["gate_profile"]
        self.assertEqual(profile["name"], "bridge_exposition_continuation")
        self.assertEqual(profile["target_mode"], "causal_bridge_scene_execution")
        self.assertEqual(profile["selection_basis"]["source"], "chapter_outline.md")
        self.assertEqual(profile["selection_basis"]["chapter_card_number"], 4)
        self.assertIn("因果", profile["selection_basis"]["matched_core_cues"])
        self.assertGreater(profile["tolerances"]["exposition_density"], 0.35)

    def test_bridge_profile_can_clear_same_bridge_metrics_without_weakening_standard(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        draft = StyleMetrics(
            label="草稿：第4章 改写与反噬",
            chars=2748,
            paragraphs=55,
            avg_para=50.0,
            sentences=121,
            avg_sentence=22.7,
            dialogue_ratio=0.62,
            interior_density=6.2,
            action_density=12.7,
            environment_density=12.7,
            exposition_density=1.5,
            suspense_density=6.6,
        )
        bridge_evidence = {
            4: {
                "number": 4,
                "title": "改写与反噬",
                "fields": {
                    "chapter_goal": "改写记录，引发因果连锁，代价由同伴承受",
                    "conflict_or_obstacle": "因果必须找一个替罪羊",
                    "payoff": "反噬重伤，改写不是免费的",
                    "constraint_refs": "WORLD_MODEL_REQUIRED",
                },
            }
        }

        standard_gate = build_style_gate([baseline, draft])
        bridge_gate = build_style_gate([baseline, draft], chapter_outline_evidence=bridge_evidence)

        self.assertEqual(standard_gate["status"], "fail")
        self.assertEqual(standard_gate["drafts"][0]["gate_profile"]["name"], "standard_continuation")
        standard_failures = {
            item["metric"]
            for item in standard_gate["drafts"][0]["items"]
            if item["severity"] == "fail"
        }
        self.assertIn("avg_para", standard_failures)
        self.assertIn("exposition_density", standard_failures)
        self.assertEqual(bridge_gate["status"], "pass")
        bridge_draft = bridge_gate["drafts"][0]
        self.assertEqual(bridge_draft["gate_profile"]["name"], "bridge_exposition_continuation")
        self.assertEqual(bridge_draft["fail_count"], 0)

    def test_bridge_profile_downgrades_scene_bound_exposition_and_suspense_only(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        scene_bound_draft = StyleMetrics(
            label="草稿：第7章 档案净化协议",
            chars=2220,
            paragraphs=41,
            avg_para=54.1,
            sentences=100,
            avg_sentence=22.2,
            dialogue_ratio=0.41,
            interior_density=7.2,
            action_density=10.8,
            environment_density=8.1,
            exposition_density=2.7,
            suspense_density=10.8,
            profile_quality={
                "paragraph_count": 41,
                "scene_bound_paragraph_count": 35,
                "scene_bound_paragraph_ratio": 0.8537,
                "action_or_environment_paragraph_count": 20,
                "action_or_environment_paragraph_ratio": 0.4878,
                "exposition_paragraph_count": 6,
                "exposition_scene_bound_count": 6,
                "exposition_scene_bound_ratio": 1.0,
                "suspense_paragraph_count": 15,
                "suspense_scene_bound_count": 12,
                "suspense_scene_bound_ratio": 0.8,
            },
        )
        bridge_evidence = {
            7: {
                "number": 7,
                "title": "档案净化协议",
                "fields": {
                    "chapter_goal": "causal cost rewrite mechanism",
                    "conflict_or_obstacle": "rule constraint WORLD_MODEL_REQUIRED",
                    "payoff": "rewrite target creates immediate cost",
                    "constraint_refs": "WORLD_MODEL_REQUIRED rule rewrite cost",
                },
            }
        }

        standard_gate = build_style_gate([baseline, scene_bound_draft])
        bridge_gate = build_style_gate([baseline, scene_bound_draft], chapter_outline_evidence=bridge_evidence)

        self.assertEqual(standard_gate["status"], "fail")
        bridge_draft = bridge_gate["drafts"][0]
        self.assertEqual(bridge_draft["gate_profile"]["name"], "bridge_exposition_continuation")
        self.assertEqual(bridge_gate["status"], "pass")
        self.assertEqual(bridge_draft["fail_count"], 0)
        self.assertEqual(bridge_draft["warn_count"], 4)
        downgraded = {
            item["metric"]: item["quality_override"]
            for item in bridge_draft["items"]
            if item.get("quality_override")
        }
        self.assertEqual(set(downgraded), {"exposition_density", "suspense_density"})
        self.assertEqual(downgraded["exposition_density"]["status"], "downgraded_to_warning")
        self.assertEqual(downgraded["suspense_density"]["status"], "downgraded_to_warning")

    def test_bridge_profile_keeps_unbound_exposition_as_failure(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        unbound_draft = StyleMetrics(
            label="草稿：第7章 抽象规则说明",
            chars=2220,
            paragraphs=41,
            avg_para=54.1,
            sentences=100,
            avg_sentence=22.2,
            dialogue_ratio=0.05,
            interior_density=1.0,
            action_density=1.0,
            environment_density=1.0,
            exposition_density=2.7,
            suspense_density=10.8,
            profile_quality={
                "paragraph_count": 41,
                "scene_bound_paragraph_count": 8,
                "scene_bound_paragraph_ratio": 0.1951,
                "action_or_environment_paragraph_count": 2,
                "action_or_environment_paragraph_ratio": 0.0488,
                "exposition_paragraph_count": 22,
                "exposition_scene_bound_count": 4,
                "exposition_scene_bound_ratio": 0.1818,
                "suspense_paragraph_count": 15,
                "suspense_scene_bound_count": 3,
                "suspense_scene_bound_ratio": 0.2,
            },
        )
        bridge_evidence = {
            7: {
                "number": 7,
                "title": "档案净化协议",
                "fields": {
                    "chapter_goal": "causal cost rewrite mechanism",
                    "conflict_or_obstacle": "rule exposition WORLD_MODEL_REQUIRED",
                    "payoff": "backlash and seventh page",
                    "constraint_refs": "WORLD_MODEL_REQUIRED rule rewrite cost",
                },
            }
        }

        gate = build_style_gate([baseline, unbound_draft], chapter_outline_evidence=bridge_evidence)

        draft_gate = gate["drafts"][0]
        self.assertEqual(draft_gate["gate_profile"]["name"], "bridge_exposition_continuation")
        self.assertEqual(gate["status"], "fail")
        failed_metrics = {
            item["metric"]
            for item in draft_gate["items"]
            if item["severity"] == "fail"
        }
        self.assertIn("exposition_density", failed_metrics)
        self.assertIn("suspense_density", failed_metrics)
        self.assertFalse(
            any(
                item.get("quality_override")
                for item in draft_gate["items"]
                if item["metric"] in {"exposition_density", "suspense_density"}
            )
        )

    def test_bridge_profile_is_not_selected_from_draft_prose_alone(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=1000,
            paragraphs=40,
            avg_para=25.0,
            sentences=40,
            avg_sentence=25.0,
            dialogue_ratio=0.4,
            interior_density=8.0,
            action_density=12.0,
            environment_density=9.0,
            exposition_density=0.8,
            suspense_density=7.0,
        )
        draft = StyleMetrics(
            label="草稿：第4章 因果代价机制桥接章",
            chars=2000,
            paragraphs=40,
            avg_para=50.0,
            sentences=80,
            avg_sentence=25.0,
            dialogue_ratio=0.4,
            interior_density=8.0,
            action_density=12.0,
            environment_density=9.0,
            exposition_density=1.5,
            suspense_density=7.0,
        )

        gate = build_style_gate([baseline, draft])

        draft_gate = gate["drafts"][0]
        self.assertEqual(draft_gate["gate_profile"]["name"], "standard_continuation")
        self.assertEqual(draft_gate["gate_profile"]["selection_basis"]["source"], "chapter_number")
        self.assertEqual(gate["status"], "fail")

    def test_arc_tail_choice_outline_evidence_takes_precedence_over_bridge_profile(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        draft = StyleMetrics(
            label="draft chapter 5",
            chars=2546,
            paragraphs=36,
            avg_para=70.7,
            sentences=95,
            avg_sentence=26.8,
            dialogue_ratio=0.72,
            interior_density=5.9,
            action_density=11.8,
            environment_density=9.0,
            exposition_density=0.4,
            suspense_density=11.4,
        )
        choice_evidence = {
            5: {
                "number": 5,
                "title": "choice-resolution",
                "fields": {
                    "chapter_goal": "弧尾 兑现 解除 代价 因果 记忆",
                    "conflict_or_obstacle": "选择 放弃 保留 守护",
                    "payoff": "选择 第三条路 控制指令 改写",
                    "ending_hook": "下一个单元 resolution",
                    "constraint_refs": "WORLD_MODEL_REQUIRED",
                },
            }
        }

        gate = build_style_gate([baseline, draft], chapter_outline_evidence=choice_evidence)

        draft_gate = gate["drafts"][0]
        profile = draft_gate["gate_profile"]
        self.assertEqual(profile["name"], "arc_tail_choice_continuation")
        self.assertEqual(profile["target_mode"], "choice_resolution_scene_execution")
        self.assertEqual(profile["selection_basis"]["reason"], "outline_card_arc_tail_choice_cues")
        self.assertEqual(profile["selection_basis"]["chapter_card_number"], 5)
        self.assertIn("弧尾", profile["selection_basis"]["matched_arc_tail_cues"])
        self.assertIn("选择", profile["selection_basis"]["matched_decision_cues"])
        self.assertNotEqual(profile["name"], "bridge_exposition_continuation")

    def test_arc_tail_choice_profile_can_clear_chapter_five_metrics_without_weakening_standard(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        draft = StyleMetrics(
            label="draft chapter 5",
            chars=2546,
            paragraphs=36,
            avg_para=70.7,
            sentences=95,
            avg_sentence=26.8,
            dialogue_ratio=0.72,
            interior_density=5.9,
            action_density=11.8,
            environment_density=9.0,
            exposition_density=0.4,
            suspense_density=11.4,
        )
        choice_evidence = {
            5: {
                "number": 5,
                "title": "choice-resolution",
                "fields": {
                    "chapter_goal": "弧尾 兑现 解除 代价 因果 记忆",
                    "conflict_or_obstacle": "选择 放弃 保留 守护",
                    "payoff": "选择 第三条路 控制指令 改写",
                    "ending_hook": "下一个单元 resolution",
                    "constraint_refs": "WORLD_MODEL_REQUIRED",
                },
            }
        }
        bridge_evidence = {
            5: {
                "number": 5,
                "title": "bridge-mechanism",
                "fields": {
                    "chapter_goal": "改写 因果 代价",
                    "conflict_or_obstacle": "因果 规则 解释",
                    "payoff": "WORLD_MODEL_REQUIRED",
                    "constraint_refs": "改写 因果 代价 机制",
                },
            }
        }

        standard_gate = build_style_gate([baseline, draft])
        bridge_gate = build_style_gate([baseline, draft], chapter_outline_evidence=bridge_evidence)
        choice_gate = build_style_gate([baseline, draft], chapter_outline_evidence=choice_evidence)

        self.assertEqual(standard_gate["status"], "fail")
        standard_failures = {
            item["metric"]
            for item in standard_gate["drafts"][0]["items"]
            if item["severity"] == "fail"
        }
        self.assertIn("avg_para", standard_failures)
        self.assertIn("dialogue_ratio", standard_failures)
        self.assertEqual(bridge_gate["status"], "fail")
        bridge_failures = {
            item["metric"]
            for item in bridge_gate["drafts"][0]["items"]
            if item["severity"] == "fail"
        }
        self.assertIn("suspense_density", bridge_failures)
        self.assertEqual(choice_gate["status"], "pass")
        choice_draft = choice_gate["drafts"][0]
        self.assertEqual(choice_draft["gate_profile"]["name"], "arc_tail_choice_continuation")
        self.assertEqual(choice_draft["fail_count"], 0)
        self.assertEqual(choice_draft["warn_count"], 3)
        warning_metrics = {
            item["metric"]
            for item in choice_draft["items"]
            if item["severity"] == "warn"
        }
        self.assertEqual(warning_metrics, {"avg_para", "dialogue_ratio", "suspense_density"})

    def test_arc_tail_choice_profile_is_not_selected_from_draft_prose_alone(self):
        baseline = StyleMetrics(
            label="baseline sample",
            chars=31596,
            paragraphs=1173,
            avg_para=26.9,
            sentences=988,
            avg_sentence=32.0,
            dialogue_ratio=0.42,
            interior_density=8.3,
            action_density=12.5,
            environment_density=9.1,
            exposition_density=0.8,
            suspense_density=7.2,
        )
        draft = StyleMetrics(
            label="draft chapter 5 arc-tail choice third path resolve",
            chars=2546,
            paragraphs=36,
            avg_para=70.7,
            sentences=95,
            avg_sentence=26.8,
            dialogue_ratio=0.72,
            interior_density=5.9,
            action_density=11.8,
            environment_density=9.0,
            exposition_density=0.4,
            suspense_density=11.4,
        )

        gate = build_style_gate([baseline, draft])

        draft_gate = gate["drafts"][0]
        self.assertEqual(draft_gate["gate_profile"]["name"], "standard_continuation")
        self.assertEqual(draft_gate["gate_profile"]["selection_basis"]["source"], "chapter_number")
        self.assertEqual(gate["status"], "fail")


if __name__ == "__main__":
    unittest.main()
