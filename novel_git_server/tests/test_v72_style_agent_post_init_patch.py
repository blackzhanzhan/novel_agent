import importlib.util
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT_DIR / "scripts" / "patch_style_agent.py"
SCAN_PATH = ROOT_DIR / "scripts" / "scan_dify_prompt_hygiene.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V72StyleAgentPostInitPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = load_module("patch_style_agent_v72", PATCH_PATH)
        cls.scan = load_module("scan_dify_prompt_hygiene_v72", SCAN_PATH)

    def test_style_prompt_hands_initialization_to_promptless_backend_pipeline(self):
        combined = f"{self.patch.STYLE_AGENT_QUERY}\n{self.patch.STYLE_AGENT_INSTRUCTION}"

        for marker in [
            "STYLE_INIT_PIPELINE_HANDOFF",
            "/api/style/init_pipeline",
            "右下角「动作」面板",
            "无提示词后台任务",
            "聊天 Agent 不得接管",
            "不得宣称自己完成初始化",
        ]:
            self.assertIn(marker, combined)

    def test_style_prompt_retains_post_init_refinement_write_path(self):
        combined = f"{self.patch.STYLE_AGENT_QUERY}\n{self.patch.STYLE_AGENT_INSTRUCTION}"

        for marker in [
            "STYLE_POST_INIT_REFINEMENT_PROTOCOL",
            "style_guide.md",
            "style_fingerprint.md",
            "style_review.md",
            "style_constraints_for_continuation.md",
            "generate_style_diagnostics 只允许作为诊断/证据工具使用",
            "draft_append_markdown_section",
            "draft_replace_markdown_section",
            "explicit_user_write",
            "本轮未写入草稿",
        ]:
            self.assertIn(marker, combined)

    def test_style_prompt_no_longer_names_agent_as_initialization_owner(self):
        self.assertNotIn("文风产物初始化 Agent", self.patch.STYLE_AGENT_INSTRUCTION)
        self.assertNotIn("STYLE_INIT_ARTIFACT_PROTOCOL", self.patch.STYLE_AGENT_QUERY)
        self.assertNotIn("STYLE_INIT_ARTIFACT_PROTOCOL", self.patch.STYLE_AGENT_INSTRUCTION)

    def test_workflow_validation_requires_handoff_markers(self):
        for marker in [
            "STYLE_INIT_PIPELINE_HANDOFF",
            "/api/style/init_pipeline",
            "右下角「动作」面板",
            "STYLE_POST_INIT_REFINEMENT_PROTOCOL",
        ]:
            self.assertIn(marker, self.patch.PROMPT_MARKERS)

    def test_style_tools_still_keep_diagnostics_and_minimal_write_tools(self):
        self.assertIn("generate_style_diagnostics", self.patch.STYLE_AGENT_TOOLS)
        self.assertIn("draft_append_markdown_section", self.patch.STYLE_AGENT_TOOLS)
        self.assertIn("draft_replace_markdown_section", self.patch.STYLE_AGENT_TOOLS)

    def test_style_prompt_and_tool_descriptions_are_chinese_generic(self):
        combined = "\n".join(
            [
                self.patch.STYLE_AGENT_QUERY,
                self.patch.STYLE_AGENT_INSTRUCTION,
                *self.patch.TOOL_DESCRIPTION_OVERRIDES.values(),
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
            "Apply this protocol",
            "Your job",
            "Do not",
            "must not",
            "Flat replace tool",
            "Dify Agents",
            "????",
        ]:
            self.assertNotIn(stale_marker, combined)

    def test_workflow_tool_entry_uses_chinese_description_override(self):
        provider_tools = [
            {
                "operation_id": "draft_replace_markdown_section",
                "summary": "Flat replace tool for Dify Agents. Content must include the target heading line.",
                "openapi": {
                    "description": "Flat replace tool for Dify Agents. Content must include the target heading line.",
                },
                "parameters": [{"name": "file_name"}],
            }
        ]

        entry = self.patch.workflow_tool_entry("draft_replace_markdown_section", provider_tools)

        self.assertEqual(
            entry["tool_description"],
            self.patch.TOOL_DESCRIPTION_OVERRIDES["draft_replace_markdown_section"],
        )
        self.assertEqual(entry["extra"]["description"], entry["tool_description"])
        self.assertEqual(entry["provider_show_name"], "LoreGit 后端工具集")


if __name__ == "__main__":
    unittest.main()
