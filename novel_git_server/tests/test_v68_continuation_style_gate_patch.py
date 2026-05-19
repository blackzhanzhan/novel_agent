import importlib.util
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT_DIR / "scripts" / "patch_continuation_agent.py"
SCAN_PATH = ROOT_DIR / "scripts" / "scan_dify_prompt_hygiene.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V68ContinuationStyleGatePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = load_module("patch_continuation_agent_v68", PATCH_PATH)
        cls.scan = load_module("scan_dify_prompt_hygiene_v68", SCAN_PATH)

    def test_continuation_workflow_exposes_style_advisory_tool(self):
        self.assertIn("validate_chapter_lengths", self.patch.CONTINUATION_TOOLS)
        self.assertIn("generate_style_diagnostics", self.patch.CONTINUATION_TOOLS)
        self.assertIn("validate_chapter_lengths", self.patch.REQUIRED_PROVIDER_OPERATIONS)
        self.assertIn("generate_style_diagnostics", self.patch.REQUIRED_PROVIDER_OPERATIONS)
        self.assertEqual(
            self.patch.OPERATION_PATHS["generate_style_diagnostics"],
            ("post", "/tools/generate_style_diagnostics"),
        )

    def test_continuation_prompt_treats_style_as_advisory_reference(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "STYLE_ADVISORY_PROTOCOL",
            "AUTHOR_STYLE_REVISION_PROTOCOL",
            "style_advisory",
            "style_advisory_diagnostics",
            "style_files_imitation_reference",
            "source_text_imitation_reference",
            "latest_source_text",
            "author_revision_owner=human_author",
            "locks_scheduler=false",
            "style_gate_not_scheduler_lock",
            "generate_style_diagnostics",
            "style_gate",
            "red_flags",
            "draft_replace_markdown_section",
            "外部助手不得直接写/改正文",
        ]:
            self.assertIn(marker, combined)

        for stale_hard_gate_marker in [
            "STYLE_GATE_PROTOCOL",
            "REPAIR_PLAN_PROTOCOL",
            "文风硬约束",
            "长度门与文风门都通过后，才能写下一章",
            "stop under the style gate instead of doing another blind expansion",
            "do not require style_gate pass before next chapter",
            "style files are imitation references",
            "source text imitation reference",
        ]:
            self.assertNotIn(stale_hard_gate_marker, combined)

    def test_continuation_prompt_mentions_opening_metric_coupling(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        self.assertIn("avg_para", combined)
        self.assertIn("avg_sentence", combined)
        self.assertIn("split_trigger", combined)
        self.assertIn("merge_trigger", combined)

    def test_length_repair_obeys_style_priority_metrics(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "LENGTH_REPAIR_STYLE_PRIORITY_PROTOCOL",
            "补足篇幅前先参考 `style_gate.drafts[].repair_plan.priority_metrics`",
            "exposition_density",
            "suspense_density",
            "禁止用解释、世界规则分析、重复提问、预言或新悬念灌水",
            "优先用具体场面节拍补足",
            "style_advisory 的 fail/warn 只报告为建议",
            "不能单独阻塞下一章",
        ]:
            self.assertIn(marker, combined)

    def test_write_loop_budget_protocol_stops_retry_after_tool_guard(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "WRITE_LOOP_BUDGET_PROTOCOL",
            "AI_WRITE_LOOP_GUARD",
            "six_recent_repair_like",
            "立即停止",
            "不要在同一轮继续尝试更小修改",
            "不要继续写后续待写章卡",
            "盲目扩写或反复局部修补已经失败",
        ]:
            self.assertIn(marker, combined)

    def test_bridge_density_repair_blocks_padding_regression(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "BRIDGE_DENSITY_REPAIR_PROTOCOL",
            "bridge_exposition_continuation",
            "four_density_failure",
            "可选修订",
            "avg_para",
            "dialogue_ratio",
            "environment_density",
            "exposition_density",
            "no_environment_padding",
            "no_q_and_a_padding",
            "scene_bound_micro_beats",
            "每个新增节拍都要保持或降低对白、环境、解释密度",
            "这个报告本身不能作为调度锁",
        ]:
            self.assertIn(marker, combined)

    def test_paragraph_environment_delta_requires_measurable_repair(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "PARAGRAPH_ENVIRONMENT_REPAIR_DELTA",
            "建议增量",
            "style_advisory 标红",
            "paragraph_count_must_increase",
            "no_merge_back_into_bulk_paragraphs",
            "environment_cue_budget",
            "environment_terms_must_decrease",
            "让 `avg_para` 变差",
            "重复环境提示簇应少于替换前",
            "不引入新气氛词",
        ]:
            self.assertIn(marker, combined)

    def test_style_metric_delta_protocol_consumes_generic_proxy_contract(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "STYLE_METRIC_DELTA_PROTOCOL",
            "style_metric_delta",
            "proxy_repair_goals",
            "protected_metrics",
            "protected_metric_regressions",
            "block_blind_expansion",
            "建议性修复证据",
            "它不是调度锁",
            "paragraph_count_must_increase",
            "average_paragraph_chars_must_decrease",
            "no_merge_split_beats",
            "environment_cue_clusters_must_decrease",
            "delete_atmosphere_only_cues",
            "length_or_size_recovery_regressed_protected_metric",
            "都是具体提示",
            "不要求 style_gate 通过才能进入下一章",
            "可以停止可选文风修订循环",
        ]:
            self.assertIn(marker, combined)

    def test_chapter_context_pack_protocol_consumes_current_chapter_brief(self):
        combined = f"{self.patch.CONTINUATION_QUERY}\n{self.patch.CONTINUATION_INSTRUCTION}"

        for marker in [
            "CHAPTER_CONTEXT_PACK_PROTOCOL",
            "chapter_context_pack",
            "当前章执行简报",
            "chapter_context_pack.chapter_number",
            "targeting.blocked_next_action",
            "chapter_card.number",
            "先修复当前章，再写待写章卡",
            "decision_chain",
            "non_negotiable_facts",
            "truth_source_refs",
            "不是隐藏正史",
            "不是人类批准",
            "pack_reads_chapter_draft_text=false",
            "pack_is_hidden_canon=false",
            "continuation_agent_remains_only_chapter_draft_writer=true",
            "不要把包当成可粘贴文本",
        ]:
            self.assertIn(marker, combined)

    def test_continuation_prompts_are_cn_generic_under_prompt_scanner(self):
        combined = "\n".join(
            [
                self.patch.CONTINUATION_QUERY,
                self.patch.CONTINUATION_INSTRUCTION,
                "\n".join(self.patch.TOOL_DESCRIPTION_OVERRIDES.values()),
            ]
        )

        issue = self.scan.inspect_text(combined, source="unit")
        if issue:
            self.assertNotIn("hardcoded", issue.categories)
            self.assertNotIn("english", issue.categories)
            self.assertNotIn("mojibake", issue.categories)

        for stale_marker in [
            "donk",
            "Major",
            "BLAST",
            "CS1.6",
            "Apply this protocol",
            "Your job",
            "Do not",
            "must not",
            "never",
        ]:
            self.assertNotIn(stale_marker, combined)

    def test_tool_descriptions_are_overridden_to_cn(self):
        provider_tools = [
            {"operation_id": tool_name, "summary": "Flat replace tool for Dify Agents.", "parameters": []}
            for tool_name in self.patch.CONTINUATION_TOOLS
        ]

        for tool_name in self.patch.CONTINUATION_TOOLS:
            entry = self.patch.workflow_tool_entry(tool_name, provider_tools)
            self.assertEqual(entry["provider_show_name"], "LoreGit 后端工具集")
            self.assertEqual(entry["tool_description"], self.patch.TOOL_DESCRIPTION_OVERRIDES[tool_name])
            self.assertEqual(entry["extra"]["description"], self.patch.TOOL_DESCRIPTION_OVERRIDES[tool_name])

    def test_start_variable_hints_are_generic(self):
        graph = {
            "nodes": [
                {
                    "id": self.patch.START_NODE_ID,
                    "data": {
                        "type": "start",
                        "variables": [
                            {"variable": "book_name", "hint": "当前书名或项目名，例如 donk。", "placeholder": "donk"},
                            {"variable": "active_file", "default": "", "required": False},
                        ],
                    },
                },
                {"data": {"type": "agent", "title": self.patch.AGENT_TITLE, "agent_parameters": {}}},
                {"data": {"type": "answer"}},
            ],
            "edges": [{}, {}],
        }

        changed = self.patch.ensure_start_variables(graph)
        variables = graph["nodes"][0]["data"]["variables"]
        by_name = {item["variable"]: item for item in variables}

        self.assertTrue(changed)
        self.assertIn("book_id", by_name)
        self.assertNotIn("donk", by_name["book_name"]["hint"])
        self.assertEqual(by_name["book_id"]["hint"], "当前书库标识。由前端桥接传入；Dify 手测时按当前书库填写。")
        self.assertEqual(by_name["active_file"]["hint"], "当前目标文件。续写链路固定为 chapter_draft.md。")
        self.assertEqual(by_name["active_file"]["default"], "chapter_draft.md")

    def test_historical_workflow_patch_only_cleans_prompt_surfaces(self):
        graph = {
            "nodes": [
                {
                    "id": self.patch.START_NODE_ID,
                    "data": {
                        "type": "start",
                        "variables": [
                            {"variable": "book_name", "hint": "当前书名或项目名，例如 donk。", "placeholder": "donk"},
                            {"variable": "active_file", "default": "", "required": False, "hint": ""},
                        ],
                    },
                },
                {
                    "data": {
                        "type": "agent",
                        "title": self.patch.AGENT_TITLE,
                        "agent_parameters": {
                            "maximum_iterations": {"type": "constant", "value": 12},
                            "query": {"type": "constant", "value": "旧 query"},
                            "instruction": {"type": "constant", "value": "旧 instruction"},
                            "tools": {
                                "type": "constant",
                                "value": [
                                    {
                                        "tool_name": "draft_replace_markdown_section",
                                        "provider_show_name": "LoreGit ?????",
                                        "tool_description": "Flat replace tool for Dify Agents. Content must include heading.",
                                        "extra": {"description": "Flat replace tool for Dify Agents."},
                                    }
                                ],
                            },
                            "model": {
                                "value": {
                                    "provider": self.patch.EXPECTED_MODEL_PROVIDER,
                                    "model": self.patch.EXPECTED_MODEL,
                                    "completion_params": {"thinking": True, "reasoning_effort": "high"},
                                }
                            },
                        },
                    }
                },
                {"data": {"type": "answer"}},
            ],
            "edges": [{}, {}],
        }

        changed = self.patch.patch_workflow(graph, [], full_runtime_patch=False)
        params = graph["nodes"][1]["data"]["agent_parameters"]
        variables = {item["variable"]: item for item in graph["nodes"][0]["data"]["variables"]}
        tool = params["tools"]["value"][0]

        self.assertTrue(changed)
        self.assertNotIn("book_id", variables)
        self.assertEqual(params["maximum_iterations"]["value"], 12)
        self.assertEqual(params["query"]["value"], "旧 query")
        self.assertEqual(params["instruction"]["value"], "旧 instruction")
        self.assertEqual(tool["provider_show_name"], "LoreGit 后端工具集")
        self.assertEqual(tool["tool_description"], self.patch.TOOL_DESCRIPTION_OVERRIDES["draft_replace_markdown_section"])


if __name__ == "__main__":
    unittest.main()
