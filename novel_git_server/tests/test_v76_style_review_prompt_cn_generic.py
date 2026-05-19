import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STYLE_PATCH_PATH = ROOT_DIR / "scripts" / "patch_style_agent.py"
REVIEW_PATCH_PATH = ROOT_DIR / "scripts" / "patch_review_agent.py"
SCAN_PATH = ROOT_DIR / "scripts" / "scan_dify_prompt_hygiene.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V76StyleReviewPromptCnGenericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.style_patch = load_module("patch_style_agent_v76", STYLE_PATCH_PATH)
        cls.review_patch = load_module("patch_review_agent_v76", REVIEW_PATCH_PATH)
        cls.scan = load_module("scan_dify_prompt_hygiene_v76", SCAN_PATH)

    def test_style_tool_overrides_are_chinese_generic_under_prompt_scanner(self):
        combined = "\n".join(self.style_patch.TOOL_DESCRIPTION_OVERRIDES.values())

        issue = self.scan.inspect_text(combined, source="unit")
        if issue:
            self.assertNotIn("hardcoded", issue.categories)
            self.assertNotIn("english", issue.categories)
            self.assertNotIn("mojibake", issue.categories)

        for stale_marker in ["donk", "Major", "Flat replace tool", "Dify Agents", "????"]:
            self.assertNotIn(stale_marker, combined)

    def test_review_script_surfaces_are_chinese_generic_under_prompt_scanner(self):
        combined = "\n".join(
            [
                *[
                    value
                    for surface in self.review_patch.START_VARIABLE_SURFACES.values()
                    for value in surface.values()
                ],
                *self.review_patch.TOOL_DESCRIPTION_OVERRIDES.values(),
            ]
        )

        issue = self.scan.inspect_text(combined, source="unit")
        if issue:
            self.assertNotIn("hardcoded", issue.categories)
            self.assertNotIn("english", issue.categories)
            self.assertNotIn("mojibake", issue.categories)

        for stale_marker in ["donk", "Major", "BLAST", "Flat append tool", "Dify Agents", "MUST", "????"]:
            self.assertNotIn(stale_marker, combined)

    def test_review_patch_cleans_start_variables_and_tool_cards_without_changing_tools(self):
        graph = self._review_graph()
        before_tools = self._tool_names(graph)

        changed = self.review_patch.patch_graph(graph)
        after_tools = self._tool_names(graph)

        self.assertTrue(changed)
        self.assertEqual(before_tools, after_tools)
        variables = graph["nodes"][0]["data"]["variables"]
        self.assertEqual(variables[0]["hint"], self.review_patch.START_VARIABLE_SURFACES["book_name"]["hint"])
        self.assertEqual(variables[0]["placeholder"], self.review_patch.START_VARIABLE_SURFACES["book_name"]["placeholder"])
        self.assertEqual(variables[1]["hint"], self.review_patch.START_VARIABLE_SURFACES["active_file"]["hint"])
        self.assertEqual(variables[1]["placeholder"], "chapter_draft.md")
        for tool in graph["nodes"][1]["data"]["agent_parameters"]["tools"]["value"]:
            self.assertEqual(tool["provider_show_name"], "LoreGit 后端工具集")
            expected = self.review_patch.TOOL_DESCRIPTION_OVERRIDES[tool["tool_name"]]
            self.assertEqual(tool["tool_description"], expected)
            self.assertEqual(tool["extra"]["description"], expected)

    def test_review_validation_rejects_stale_prompt_surfaces(self):
        graph = self._review_graph()

        with self.assertRaises(RuntimeError):
            self.review_patch.validate_workflow(graph, label="unit")

        self.review_patch.patch_graph(graph)
        result = self.review_patch.validate_workflow(graph, label="unit")

        self.assertEqual(result["nodes"], 3)
        self.assertEqual(result["edges"], 2)
        self.assertEqual(result["tools"], ["draft_append_markdown_section", "draft_replace_markdown_section"])

    def _review_graph(self):
        return {
            "nodes": [
                {
                    "data": {
                        "type": "start",
                        "variables": [
                            {
                                "variable": "book_name",
                                "label": "book_name",
                                "hint": "??????????? donk?",
                                "placeholder": "donk",
                                "required": True,
                                "type": "text-input",
                            },
                            {
                                "variable": "active_file",
                                "label": "active_file",
                                "hint": "??????????? chapter_draft.md?",
                                "placeholder": "chapter_draft.md",
                                "required": True,
                                "type": "text-input",
                            },
                        ],
                    }
                },
                {
                    "data": {
                        "type": "agent",
                        "title": "REVIEW_AGENT",
                        "agent_parameters": {
                            "model": {
                                "value": {
                                    "provider": self.review_patch.EXPECTED_MODEL_PROVIDER,
                                    "model": self.review_patch.EXPECTED_MODEL,
                                    "completion_params": {"thinking": True},
                                }
                            },
                            "tools": {
                                "value": [
                                    self._tool("draft_append_markdown_section", "Flat append tool for Dify Agents. MUST be ????"),
                                    self._tool("draft_replace_markdown_section", "Flat replace tool for Dify Agents. Content must include the heading."),
                                ]
                            },
                        },
                    }
                },
                {"data": {"type": "answer"}},
            ],
            "edges": [{"id": "1"}, {"id": "2"}],
        }

    @staticmethod
    def _tool(name: str, description: str):
        return {
            "tool_name": name,
            "provider_show_name": "LoreGit ?????",
            "tool_description": description,
            "extra": {"description": description},
        }

    @staticmethod
    def _tool_names(graph):
        tools = graph["nodes"][1]["data"]["agent_parameters"]["tools"]["value"]
        return deepcopy([tool["tool_name"] for tool in tools])


if __name__ == "__main__":
    unittest.main()
