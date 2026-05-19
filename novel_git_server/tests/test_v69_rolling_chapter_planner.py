import shutil
import sys
import unittest
import uuid
import json
from pathlib import Path
import importlib.util


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipelines.rolling_chapter import (  # noqa: E402
    build_chapter_context_pack,
    build_human_unlock_artifact,
    build_rolling_plan,
    build_review_packet,
    build_style_repair_delta,
    evaluate_human_unlock,
    parse_chapter_cards,
    parse_chapter_number,
    summarize_style_gate_artifact,
)


BRIDGE_SCRIPT = ROOT_DIR.parent / "scripts" / "rolling_review_bridge.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("rolling_review_bridge", BRIDGE_SCRIPT)
assert BRIDGE_SPEC is not None and BRIDGE_SPEC.loader is not None
rolling_review_bridge = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(rolling_review_bridge)


def card(number: int, title: str) -> str:
    return f"""## 章节卡 {number}：{title}

- chapter_goal：目标
- entry_scene：入场
- conflict_or_obstacle：阻碍
- payoff：兑现
- state_change：状态变化
- foreshadowing_action：伏笔动作
- ending_hook：尾钩
- constraint_refs：约束
- evidence_mode：AUTHOR_PROPOSAL
"""


def bold_ch_card(number: int, title: str) -> str:
    return f"""### CH{number} — {title}

**章节目标**：目标{number}

**入场场景**：入场{number}

**冲突/阻碍**：阻碍{number}

**当章兑现**：兑现{number}

**状态变化**：状态{number}

**伏笔动作**：伏笔{number}

**结尾钩子**：尾钩{number}

**约束引用**：约束{number}

**证据模式**：AUTHOR_PROPOSAL
"""


class V69RollingChapterPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v69_rolling_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_chapter_number_accepts_fullwidth_and_chinese(self):
        self.assertEqual(parse_chapter_number("４"), 4)
        self.assertEqual(parse_chapter_number("十三"), 13)
        self.assertEqual(parse_chapter_number("二十"), 20)

    def test_parse_cards_marks_missing_fields(self):
        cards = parse_chapter_cards("## 章节卡 1：短卡\n\n- chapter_goal：目标\n")

        self.assertEqual(len(cards), 1)
        self.assertFalse(cards[0].executable)
        self.assertIn("entry_scene", cards[0].missing_fields)

    def test_parse_cards_accepts_ch_heading_and_bold_chinese_fields(self):
        cards = parse_chapter_cards("# 逐章大纲\n\n" + bold_ch_card(153, "伊甸园的钟"))

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].number, 153)
        self.assertEqual(cards[0].title, "伊甸园的钟")
        self.assertTrue(cards[0].executable)
        self.assertEqual(cards[0].fields["chapter_goal"], "目标153")
        self.assertEqual(cards[0].fields["entry_scene"], "入场153")
        self.assertEqual(cards[0].fields["conflict_or_obstacle"], "阻碍153")
        self.assertEqual(cards[0].fields["payoff"], "兑现153")
        self.assertEqual(cards[0].fields["ending_hook"], "尾钩153")

    def test_current_donk_style_outline_selects_ch_cards(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# 逐章大纲\n\n## 卡托维兹阶段（CH153-CH165，13章）\n\n"
            + "\n---\n\n".join(
                bold_ch_card(number, title)
                for number, title in (
                    (153, "伊甸园的钟"),
                    (154, "1200万的影子"),
                    (155, "Veto桌上的神"),
                )
            ),
            encoding="utf-8",
        )
        draft_path = self.temp_dir / "chapter_draft.md"
        if draft_path.exists():
            draft_path.unlink()

        plan = build_rolling_plan(book_id="book", book_dir=self.temp_dir, batch_size=3)

        self.assertEqual(plan["outline_card_count"], 3)
        self.assertEqual(plan["executable_card_count"], 3)
        self.assertEqual(plan["next_action"], "continue_existing_cards")
        self.assertEqual(plan["selected_card_numbers"], [153, 154, 155])
        self.assertEqual([card["title"] for card in plan["selected_cards"]], ["伊甸园的钟", "1200万的影子", "Veto桌上的神"])

    def test_current_case_selects_remaining_cards_then_replenishment(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# 逐章大纲\n\n" + "\n".join(card(i, f"标题{i}") for i in range(1, 6)),
            encoding="utf-8",
        )
        (self.temp_dir / "chapter_draft.md").write_text(
            "# 续写草稿\n\n"
            "## 第1章 标题1\n正文\n"
            "## 第2章 标题2\n正文\n"
            "## 第3章 标题3\n正文\n",
            encoding="utf-8",
        )

        plan = build_rolling_plan(book_id="book", book_dir=self.temp_dir, batch_size=3)

        self.assertEqual(plan["next_action"], "continue_existing_cards")
        self.assertEqual(plan["written_chapter_numbers"], [])
        self.assertEqual(plan["accepted_chapter_numbers"], [])
        self.assertEqual(plan["pending_review_chapter_numbers"], [1, 2, 3])
        self.assertEqual(plan["pending_card_numbers"], [4, 5])
        self.assertEqual(plan["selected_card_numbers"], [4, 5])
        self.assertFalse(plan["full_batch_available"])
        self.assertTrue(plan["replenishment_needed_after_selected_batch"])

    def test_depleted_cards_request_outline_replenishment(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# 逐章大纲\n\n" + "\n".join(card(i, f"标题{i}") for i in range(1, 4)),
            encoding="utf-8",
        )
        (self.temp_dir / "chapter_draft.md").write_text(
            "# 续写草稿\n\n"
            "## 第1章 标题1\n正文\n"
            "## 第2章 标题2\n正文\n"
            "## 第3章 标题3\n正文\n",
            encoding="utf-8",
        )

        plan = build_rolling_plan(book_id="book", book_dir=self.temp_dir, batch_size=3)

        self.assertEqual(plan["next_action"], "replenish_outline")
        self.assertEqual(plan["stop_reason"], "no_executable_pending_cards")
        self.assertEqual(plan["selected_card_numbers"], [])

    def test_quality_gate_lock_blocks_replenishment_after_depleted_cards(self):
        (self.temp_dir / "chapter_outline.md").write_text("# 閫愮珷澶х翰\n\n", encoding="utf-8")
        (self.temp_dir / "chapter_draft.md").write_text("# 缁啓鑽夌\n\n", encoding="utf-8")

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_3_style_gate_failed",
            quality_gate_source=".runtime/style.json",
            quality_gate_summary={"fail_metrics": ["suspense_density"]},
        )

        self.assertEqual(plan["next_action"], "await_quality_gate")
        self.assertEqual(plan["blocked_next_action"], "replenish_outline")
        self.assertEqual(plan["stop_reason"], "chapter_3_style_gate_failed")
        self.assertTrue(plan["quality_gate_locked"])
        self.assertEqual(plan["quality_gate_source"], ".runtime/style.json")
        self.assertEqual(plan["quality_gate_summary"]["fail_metrics"], ["suspense_density"])
        self.assertFalse(plan["quality_gate_unlocked"])
        self.assertEqual(plan["human_unlock_evaluation"]["status"], "missing")

    def test_style_gate_failure_is_advisory_and_does_not_lock_scheduler(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# 逐章大纲\n\n" + "\n".join(card(i, f"标题{i}") for i in range(1, 9)),
            encoding="utf-8",
        )
        (self.temp_dir / "chapter_draft.md").write_text(
            "# 续写草稿\n\n" + "\n".join(f"## 第{i}章 标题{i}\n正文\n" for i in range(1, 7)),
            encoding="utf-8",
        )
        style_summary = summarize_style_gate_artifact(
            {
                "style_gate": {
                    "status": "fail",
                    "overall_pass": False,
                    "drafts": [
                        {
                            "status": "fail",
                            "pass": False,
                            "fail_count": 2,
                            "warn_count": 1,
                            "items": [
                                {"metric": "action_density", "severity": "fail"},
                                {"metric": "environment_density", "severity": "fail"},
                                {"metric": "dialogue_ratio", "severity": "warn"},
                            ],
                        }
                    ],
                }
            }
        )

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_6_style_gate_failed",
            quality_gate_source=".runtime/ch6_style.json",
            quality_gate_summary=style_summary,
        )

        self.assertEqual(plan["next_action"], "continue_existing_cards")
        self.assertEqual(plan["blocked_next_action"], "")
        self.assertFalse(plan["quality_gate_locked"])
        self.assertFalse(plan["quality_gate_unlocked"])
        self.assertTrue(plan["style_advisory_active"])
        self.assertEqual(plan["style_advisory_summary"]["fail_metrics"], ["action_density", "environment_density"])
        self.assertFalse(plan["style_advisory_summary"]["locks_scheduler"])
        self.assertEqual(plan["selected_card_numbers"], [7, 8])

    def test_review_recommendation_cannot_unlock_quality_gate(self):
        (self.temp_dir / "chapter_outline.md").write_text("# outline\n\n", encoding="utf-8")
        (self.temp_dir / "chapter_draft.md").write_text("# draft\n\n", encoding="utf-8")

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_3_style_gate_failed",
            quality_gate_source=".runtime/style.json",
            human_unlock={
                "artifact_type": "review_recommendation",
                "decision": "approve_override",
                "book_id": "book",
                "chapter_number": 0,
                "quality_gate_source": ".runtime/style.json",
                "blocked_next_action": "replenish_outline",
            },
        )

        self.assertEqual(plan["next_action"], "await_quality_gate")
        self.assertEqual(plan["blocked_next_action"], "replenish_outline")
        self.assertFalse(plan["quality_gate_unlocked"])
        self.assertEqual(plan["human_unlock_evaluation"]["status"], "rejected")
        self.assertIn("artifact_type_must_be_rolling_human_unlock", plan["human_unlock_evaluation"]["reasons"])

    def test_stale_human_unlock_cannot_release_quality_gate(self):
        (self.temp_dir / "chapter_outline.md").write_text("# outline\n\n", encoding="utf-8")
        (self.temp_dir / "chapter_draft.md").write_text("# draft\n\n", encoding="utf-8")

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_3_style_gate_failed",
            quality_gate_source=".runtime/style.json",
            human_unlock={
                "artifact_type": "rolling_human_unlock",
                "status": "active",
                "decision": "approve_override",
                "human_actor": "author",
                "reason": "demo override",
                "book_id": "book",
                "chapter_number": 0,
                "quality_gate_source": ".runtime/other-style.json",
                "blocked_next_action": "replenish_outline",
            },
        )

        self.assertEqual(plan["next_action"], "await_quality_gate")
        self.assertFalse(plan["quality_gate_unlocked"])
        self.assertEqual(plan["human_unlock_evaluation"]["status"], "rejected")
        self.assertIn("quality_gate_source_mismatch", plan["human_unlock_evaluation"]["reasons"])

    def test_human_unlock_requires_chapter_binding(self):
        (self.temp_dir / "chapter_outline.md").write_text("# outline\n\n", encoding="utf-8")
        (self.temp_dir / "chapter_draft.md").write_text("# draft\n\n", encoding="utf-8")

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_style_gate_failed",
            quality_gate_source=".runtime/style.json",
            human_unlock={
                "artifact_type": "rolling_human_unlock",
                "status": "active",
                "decision": "approve_override",
                "human_actor": "author",
                "reason": "demo override",
                "book_id": "book",
                "chapter_number": None,
                "quality_gate_source": ".runtime/style.json",
                "blocked_next_action": "replenish_outline",
            },
        )

        self.assertEqual(plan["next_action"], "await_quality_gate")
        self.assertFalse(plan["quality_gate_unlocked"])
        self.assertEqual(plan["human_unlock_evaluation"]["status"], "rejected")
        self.assertIn("chapter_number_missing", plan["human_unlock_evaluation"]["reasons"])

    def test_bound_human_unlock_releases_blocked_replenishment(self):
        (self.temp_dir / "chapter_outline.md").write_text("# outline\n\n", encoding="utf-8")
        (self.temp_dir / "chapter_draft.md").write_text(
            "# draft\n\n## 第8章 标题\n正文\n",
            encoding="utf-8",
        )

        blocked_plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_3_style_gate_failed",
            quality_gate_source=".runtime/style.json",
        )
        unlock = build_human_unlock_artifact(
            plan=blocked_plan,
            human_actor="author",
            reason="demo-grade continuation approved by human",
            generated_at="2026-05-14T00:00:00+00:00",
            artifact_id="unlock",
        )

        self.assertTrue(evaluate_human_unlock(blocked_plan, unlock)["accepted"])

        released_plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_3_style_gate_failed",
            quality_gate_source=".runtime/style.json",
            human_unlock=unlock,
        )

        self.assertEqual(released_plan["next_action"], "replenish_outline")
        self.assertEqual(released_plan["stop_reason"], "human_unlock_accepted")
        self.assertTrue(released_plan["quality_gate_locked"])
        self.assertTrue(released_plan["quality_gate_unlocked"])
        self.assertEqual(released_plan["human_unlock_evaluation"]["status"], "accepted")

    def test_style_summary_reads_gate_profile_from_draft_schema(self):
        artifact = {
            "metrics": [
                {"label": "baseline"},
                {
                    "label": "draft",
                    "profile_quality": {"scene_bound_paragraph_ratio": 0.95},
                },
            ],
            "style_gate": {
                "status": "fail",
                "overall_pass": False,
                "drafts": [
                    {
                        "status": "fail",
                        "pass": False,
                        "fail_count": 1,
                        "warn_count": 1,
                        "gate_profile": {
                            "name": "bridge_exposition_continuation",
                            "target_mode": "causal_bridge_scene_execution",
                        },
                        "items": [
                            {"metric": "suspense_density", "severity": "fail"},
                            {"metric": "interior_density", "severity": "warn"},
                        ],
                        "repair_plan": {
                            "status": "required",
                            "priority_metrics": [
                                {"metric": "suspense_density", "severity": "fail"},
                            ],
                        },
                    }
                ],
            },
        }

        summary = summarize_style_gate_artifact(artifact)

        self.assertEqual(summary["profile_name"], "bridge_exposition_continuation")
        self.assertEqual(summary["target_mode"], "causal_bridge_scene_execution")
        self.assertEqual(summary["fail_metrics"], ["suspense_density"])
        self.assertEqual(summary["warn_metrics"], ["interior_density"])
        self.assertEqual(summary["profile_quality"], {"scene_bound_paragraph_ratio": 0.95})

    def test_repair_delta_flags_added_hard_failures_even_when_primary_metric_improves(self):
        before = {
            "style_gate": {
                "status": "fail",
                "overall_pass": False,
                "drafts": [
                    {
                        "status": "fail",
                        "pass": False,
                        "fail_count": 1,
                        "warn_count": 1,
                        "gate_profile": {"name": "bridge_exposition_continuation"},
                        "items": [
                            {"metric": "dialogue_ratio", "severity": "pass", "value": 0.62},
                            {"metric": "interior_density", "severity": "warn", "value": 5.4},
                            {"metric": "suspense_density", "severity": "fail", "value": 13.8},
                        ],
                        "repair_plan": {
                            "status": "required",
                            "priority_metrics": [
                                {"metric": "suspense_density", "severity": "fail", "direction": "decrease"}
                            ],
                        },
                    }
                ],
            }
        }
        after = {
            "style_gate": {
                "status": "fail",
                "overall_pass": False,
                "drafts": [
                    {
                        "status": "fail",
                        "pass": False,
                        "fail_count": 3,
                        "warn_count": 0,
                        "gate_profile": {"name": "bridge_exposition_continuation"},
                        "items": [
                            {"metric": "dialogue_ratio", "severity": "fail", "value": 0.68},
                            {"metric": "interior_density", "severity": "fail", "value": 4.9},
                            {"metric": "suspense_density", "severity": "fail", "value": 13.4},
                        ],
                        "repair_plan": {"status": "required", "priority_metrics": []},
                    }
                ],
            }
        }

        delta = build_style_repair_delta(before, after)

        self.assertEqual(delta["verdict"], "regressed")
        self.assertEqual(delta["hard_failures"]["added"], ["dialogue_ratio", "interior_density"])
        self.assertEqual(delta["hard_failures"]["persistent"], ["suspense_density"])
        suspense = {item["metric"]: item for item in delta["metric_deltas"]}["suspense_density"]
        self.assertTrue(suspense["improved_toward_repair_direction"])
        self.assertFalse(delta["acceptance"]["no_added_hard_failures"])
        contract = delta["style_metric_delta"]
        self.assertEqual(contract["protocol"], "STYLE_METRIC_DELTA_PROTOCOL")
        self.assertTrue(contract["advisory"])
        self.assertFalse(contract["locks_scheduler"])
        self.assertFalse(contract["stop_conditions"]["block_next_chapter"])
        self.assertFalse(contract["stop_conditions"]["scheduler_lock"])
        self.assertTrue(contract["stop_conditions"]["block_blind_expansion"])
        self.assertIn("added_hard_failures", contract["stop_conditions"]["reasons"])
        goals = {item["metric"]: item for item in contract["proxy_repair_goals"]}
        self.assertIn("dialogue_ratio", goals)
        self.assertIn("dialogue_paragraph_ratio_must_decrease", goals["dialogue_ratio"]["proxy_targets"])
        self.assertFalse(contract["no_prose_boundary"]["delta_contains_chapter_prose"])

    def test_style_metric_delta_flags_c2j_to_c2k_paragraph_regression_without_chapter_hardcode(self):
        runtime = ROOT_DIR.parent / ".runtime"
        before = json.loads(
            (runtime / "rolling_30_cycle2j_ch10_bridge_density_repair_style_20260514.json").read_text(
                encoding="utf-8"
            )
        )
        after = json.loads(
            (runtime / "rolling_30_cycle2k_ch10_length_style_repair_style_20260514.json").read_text(
                encoding="utf-8"
            )
        )

        delta = build_style_repair_delta(before, after)
        contract = delta["style_metric_delta"]
        metric_map = {item["metric"]: item for item in delta["metric_deltas"]}
        goals = {item["metric"]: item for item in contract["proxy_repair_goals"]}

        self.assertEqual(contract["protocol"], "STYLE_METRIC_DELTA_PROTOCOL")
        self.assertEqual(contract["profile_name"], "bridge_exposition_continuation")
        self.assertIn("avg_para", contract["protected_metric_regressions"])
        self.assertFalse(metric_map["avg_para"]["improved_toward_repair_direction"])
        self.assertTrue(metric_map["environment_density"]["improved_toward_repair_direction"])
        self.assertIn("paragraph_count_must_increase", goals["avg_para"]["proxy_targets"])
        self.assertEqual(goals["avg_para"]["proxy_state"]["before_paragraphs"], 38)
        self.assertEqual(goals["avg_para"]["proxy_state"]["after_paragraphs"], 34)
        self.assertEqual(goals["avg_para"]["proxy_state"]["paragraph_delta"], -4)
        self.assertIn("environment_cue_clusters_must_decrease", goals["environment_density"]["proxy_targets"])
        self.assertFalse(contract["stop_conditions"]["block_next_chapter"])
        self.assertFalse(contract["stop_conditions"]["scheduler_lock"])
        self.assertTrue(contract["advisory"])
        self.assertIn("protected_metric_regressed", contract["stop_conditions"]["reasons"])
        self.assertIn("length_or_size_recovery_regressed_protected_metric", contract["stop_conditions"]["reasons"])
        self.assertTrue(contract["no_prose_boundary"]["continuation_agent_remains_only_chapter_draft_writer"])

    def test_review_packet_keeps_quality_gate_block_no_prose_boundary(self):
        plan = {
            "book_id": "book",
            "batch_size": 3,
            "quality_gate_locked": True,
            "quality_gate_reason": "chapter_8_style_gate_failed",
            "quality_gate_source": ".runtime/ch8_style.json",
            "next_action": "await_quality_gate",
            "blocked_next_action": "replenish_outline",
            "stop_reason": "chapter_8_style_gate_failed",
            "outline_card_count": 8,
            "executable_card_count": 8,
            "written_chapter_count": 8,
            "written_chapter_numbers": [1, 2, 3, 4, 5, 6, 7, 8],
            "pending_card_numbers": [],
            "selected_card_numbers": [],
            "full_batch_available": False,
            "replenishment_needed_after_selected_batch": False,
            "quality_gate_summary": {
                "status": "fail",
                "overall_pass": False,
                "profile_name": "bridge_exposition_continuation",
                "target_mode": "causal_bridge_scene_execution",
                "fail_count": 3,
                "warn_count": 1,
                "fail_metrics": ["dialogue_ratio", "interior_density", "suspense_density"],
                "warn_metrics": ["avg_sentence"],
                "repair_plan_status": "required",
                "priority_metrics": [
                    {
                        "metric": "suspense_density",
                        "severity": "fail",
                        "direction": "decrease",
                        "current_value": 13.4,
                        "actions": ["should_not_be_copied"],
                    }
                ],
            },
            "cards": [
                {
                    "number": 8,
                    "fields": {
                        "chapter_goal": "must not be copied into packet",
                    },
                }
            ],
        }
        delta = {
            "verdict": "regressed",
            "score": {"before_failure_score": 110, "after_failure_score": 310, "delta": 200},
            "hard_failures": {"added": ["dialogue_ratio", "interior_density"], "persistent": ["suspense_density"]},
            "metric_deltas": [
                {
                    "metric": "suspense_density",
                    "before_severity": "fail",
                    "after_severity": "fail",
                    "before_value": 13.8,
                    "after_value": 13.4,
                    "repair_direction": "decrease",
                    "improved_toward_repair_direction": True,
                }
            ],
        }

        packet = build_review_packet(plan=plan, repair_delta=delta, generated_at="2026-05-14T00:00:00+00:00")
        packet_text = repr(packet)

        self.assertEqual(packet["packet_type"], "rolling_quality_gate_review_packet")
        self.assertEqual(packet["chapter_number"], 8)
        self.assertEqual(packet["gate"]["next_action"], "await_quality_gate")
        self.assertEqual(packet["gate"]["blocked_next_action"], "replenish_outline")
        self.assertEqual(packet["review_scope"]["review_agent_focus"], "story_conflict_and_consistency")
        self.assertTrue(packet["review_scope"]["style_is_scheduler_advisory_only"])
        self.assertTrue(packet["unlock_policy"]["requires_explicit_human_unlock"])
        self.assertFalse(packet["unlock_policy"]["review_recommendation_can_unlock"])
        self.assertEqual(packet["review_route"]["writable_files"], ["error_archive.md"])
        self.assertIn("chapter_draft.md", packet["review_route"]["forbidden_write_files"])
        self.assertEqual(packet["repair_delta"]["verdict"], "regressed")
        self.assertIn("style_metric_delta", packet["repair_delta"])
        self.assertNotIn("cards", packet)
        self.assertNotIn("chapter_goal", packet_text)
        self.assertNotIn("must not be copied", packet_text)
        self.assertNotIn("should_not_be_copied", packet_text)
        self.assertTrue(packet["no_prose_boundary"]["packet_omits_chapter_draft_text"])
        self.assertTrue(packet["no_prose_boundary"]["packet_omits_outline_card_fields"])

    def test_chapter_context_pack_targets_locked_written_chapter_without_draft_prose(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# outline\n\n"
            + "\n".join(card(i, f"title{i}") for i in range(1, 12)),
            encoding="utf-8",
        )
        draft_text = "# draft\n\n" + "\n".join(
            f"## 绗?绔?title{i}\nUNIQUE_DRAFT_PROSE_{i}\n" for i in range(1, 11)
        )
        (self.temp_dir / "chapter_draft.md").write_text(draft_text, encoding="utf-8")
        for name in (
            "world_model.md",
            "status_card.md",
            "domain_rules.md",
            "summary.md",
            "style_constraints_for_continuation.md",
            "error_archive.md",
        ):
            (self.temp_dir / name).write_text(f"# {name}\ntruth source\n", encoding="utf-8")

        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_10_style_gate_failed",
            quality_gate_source=".runtime/ch10_style.json",
            quality_gate_summary={
                "status": "fail",
                "overall_pass": False,
                "fail_metrics": ["avg_para", "environment_density"],
                "warn_metrics": ["avg_sentence"],
            },
        )
        delta = {
            "status": "success",
            "verdict": "blocked",
            "style_metric_delta": {
                "protocol": "STYLE_METRIC_DELTA_PROTOCOL",
                "proxy_repair_goals": [{"metric": "avg_para", "proxy_targets": ["paragraph_count_must_increase"]}],
                "protected_metrics": [{"metric": "avg_para", "regressed": False}],
                "protected_metric_regressions": [],
                "stop_conditions": {"block_next_chapter": True},
            },
        }

        pack = build_chapter_context_pack(
            plan=plan,
            book_dir=self.temp_dir,
            repair_delta=delta,
            generated_at="2026-05-15T00:00:00+00:00",
            pack_id="pack",
            gate_artifacts=[".runtime/ch10_style.json"],
        )
        pack_text = repr(pack)

        self.assertEqual(pack["protocol"], "CHAPTER_CONTEXT_PACK_PROTOCOL")
        self.assertEqual(pack["chapter_number"], 10)
        self.assertEqual(pack["targeting"]["blocked_next_action"], "continue_existing_cards")
        self.assertEqual(pack["chapter_card"]["number"], 10)
        self.assertIn("chapter_goal", pack["chapter_card"]["fields"])
        self.assertEqual(pack["decision_chain"]["obstacle"], pack["chapter_card"]["fields"]["conflict_or_obstacle"])
        self.assertEqual(pack["active_repair_goals"]["protocol"], "STYLE_METRIC_DELTA_PROTOCOL")
        self.assertIn("chapter_outline.md", pack["truth_source_refs"])
        self.assertIn("quality_gate_source", pack["truth_source_refs"])
        self.assertFalse(pack["no_prose_boundary"]["pack_reads_chapter_draft_text"])
        self.assertTrue(pack["no_prose_boundary"]["continuation_agent_remains_only_chapter_draft_writer"])
        self.assertNotIn("UNIQUE_DRAFT_PROSE_10", pack_text)
        self.assertNotIn("UNIQUE_DRAFT_PROSE_11", pack_text)

    def test_chapter_context_pack_carries_style_advisory_without_scheduler_lock(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# outline\n\n" + "\n".join(card(i, f"title{i}") for i in range(1, 9)),
            encoding="utf-8",
        )
        (self.temp_dir / "chapter_draft.md").write_text(
            "# draft\n\n" + "\n".join(f"## 第{i}章 title{i}\n正文\n" for i in range(1, 7)),
            encoding="utf-8",
        )
        style_summary = summarize_style_gate_artifact(
            {
                "style_gate": {
                    "status": "fail",
                    "overall_pass": False,
                    "drafts": [
                        {
                            "status": "fail",
                            "pass": False,
                            "fail_count": 1,
                            "warn_count": 0,
                            "items": [{"metric": "environment_density", "severity": "fail"}],
                        }
                    ],
                }
            }
        )
        plan = build_rolling_plan(
            book_id="book",
            book_dir=self.temp_dir,
            batch_size=3,
            quality_gate_locked=True,
            quality_gate_reason="chapter_6_style_gate_failed",
            quality_gate_source=".runtime/ch6_style.json",
            quality_gate_summary=style_summary,
        )

        pack = build_chapter_context_pack(plan=plan, book_dir=self.temp_dir)

        self.assertFalse(pack["quality_gate"]["locked"])
        self.assertFalse(pack["quality_gate"]["blocks_next_action"])
        self.assertTrue(pack["style_advisory"]["active"])
        self.assertTrue(pack["style_advisory"]["reference_only"])
        self.assertFalse(pack["style_advisory"]["blocks_next_action"])
        self.assertEqual(pack["style_advisory"]["revision_owner"], "human_author")

    def test_chapter_context_pack_marks_world_model_required_as_non_promotable(self):
        plan = {
            "book_id": "book",
            "next_action": "continue_existing_cards",
            "selected_card_numbers": [1],
            "pending_card_numbers": [1],
            "written_chapter_numbers": [],
            "cards": [
                {
                    "number": 1,
                    "title": "title",
                    "executable": True,
                    "missing_fields": [],
                    "fields": {
                        "chapter_goal": "goal",
                        "entry_scene": "entry",
                        "conflict_or_obstacle": "obstacle",
                        "payoff": "payoff",
                        "state_change": "state",
                        "foreshadowing_action": "foreshadow",
                        "ending_hook": "hook",
                        "constraint_refs": "WORLD_MODEL_REQUIRED; SOURCE_FACT",
                        "evidence_mode": "WORLD_MODEL_REQUIRED",
                    },
                }
            ],
        }
        pack = build_chapter_context_pack(plan=plan, book_dir=self.temp_dir)

        self.assertEqual(pack["chapter_number"], 1)
        self.assertEqual(pack["non_negotiable_facts"]["unresolved_world_model_required_count"], 1)
        self.assertIn(
            "WORLD_MODEL_REQUIRED_must_not_be_promoted_to_source_fact_inside_context_pack",
            pack["non_negotiable_facts"]["forbidden_promotions"],
        )
        self.assertFalse(pack["no_prose_boundary"]["pack_contains_generated_prose"])

    def test_review_bridge_payload_forces_review_agent_without_outline_fields(self):
        packet = build_review_packet(
            plan={
                "book_id": "book",
                "batch_size": 3,
                "quality_gate_locked": True,
                "quality_gate_reason": "chapter_8_style_gate_failed",
                "quality_gate_source": ".runtime/ch8_style.json",
                "next_action": "await_quality_gate",
                "blocked_next_action": "replenish_outline",
                "stop_reason": "chapter_8_style_gate_failed",
                "outline_card_count": 8,
                "executable_card_count": 8,
                "written_chapter_count": 8,
                "written_chapter_numbers": [1, 2, 3, 4, 5, 6, 7, 8],
                "pending_card_numbers": [],
                "selected_card_numbers": [],
                "quality_gate_summary": {
                    "status": "fail",
                    "overall_pass": False,
                    "fail_metrics": ["suspense_density"],
                    "priority_metrics": [
                        {
                            "metric": "suspense_density",
                            "severity": "fail",
                            "actions": ["do_not_copy"],
                        }
                    ],
                },
                "cards": [{"fields": {"chapter_goal": "do_not_copy"}}],
            },
            repair_delta={"verdict": "blocked", "metric_deltas": []},
        )

        payload = rolling_review_bridge.build_deduce_payload(packet, thread_id="review-thread")
        payload_text = repr(payload)

        self.assertEqual(payload["route_agent_key"], "review_agent")
        self.assertEqual(payload["active_file"], "chapter_draft.md")
        self.assertEqual(payload["file_type"], "chapter")
        self.assertEqual(payload["thread_id"], "review-thread")
        self.assertIn("plot continuity", payload["intent"])
        self.assertIn("Style diagnostics are advisory hints", payload["intent"])
        self.assertIn("recommendation is advisory and cannot unlock", payload["intent"])
        self.assertIn("request_continuation_repair", payload["intent"])
        self.assertNotIn("chapter_goal", payload_text)
        self.assertNotIn("do_not_copy", payload_text)

    def test_archived_chapters_drive_accepted_cursor_and_draft_is_pending_review(self):
        (self.temp_dir / "chapter_outline.md").write_text(
            "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(153, 159)),
            encoding="utf-8",
        )
        chapters_dir = self.temp_dir / "chapters"
        chapters_dir.mkdir()
        for number in range(153, 156):
            (chapters_dir / f"{number:04d}_第{number}章_title-{number}.md").write_text(
                f"## 第{number}章 title-{number}\naccepted-{number}\n",
                encoding="utf-8",
            )
        (self.temp_dir / "chapter_draft.md").write_text(
            "# 续写草稿\n\n"
            "## 第156章 title-156\npending-review-156\n",
            encoding="utf-8",
        )

        plan = build_rolling_plan(book_id="book", book_dir=self.temp_dir, batch_size=3)

        self.assertEqual(plan["written_chapter_numbers"], [153, 154, 155])
        self.assertEqual(plan["accepted_chapter_numbers"], [153, 154, 155])
        self.assertEqual(plan["pending_review_chapter_numbers"], [156])
        self.assertEqual(plan["pending_card_numbers"], [157, 158])
        self.assertEqual(plan["selected_card_numbers"], [157, 158])
        self.assertEqual(
            [chapter["source"] for chapter in plan["accepted_chapters"]],
            [
                "chapters/0153_第153章_title-153.md",
                "chapters/0154_第154章_title-154.md",
                "chapters/0155_第155章_title-155.md",
            ],
        )
        self.assertEqual(plan["pending_review_chapters"][0]["source"], "chapter_draft.md")


if __name__ == "__main__":
    unittest.main()
