import importlib.util
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT_DIR / "scripts" / "patch_outline_agent.py"
SCAN_PATH = ROOT_DIR / "scripts" / "scan_dify_prompt_hygiene.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V74OutlinePromptCnGenericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = load_module("patch_outline_agent_v74", PATCH_PATH)
        cls.scan = load_module("scan_dify_prompt_hygiene_v74", SCAN_PATH)

    def test_outline_prompts_are_chinese_generic_and_search_aware(self):
        combined = "\n".join(
            [
                self.patch.OUTLINE_PRODUCTION_CONTROL_PROTOCOL,
                self.patch.OUTLINE_IDEATION_PROTOCOL,
                self.patch.OUTLINE_SEARCH_REFERENCE_PROTOCOL,
                self.patch.OUTLINE_LANDING_PROTOCOL,
                self.patch.OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL,
                self.patch.DISCUSS_QUERY,
                self.patch.DISCUSS_INSTRUCTION,
                self.patch.COMMIT_QUERY,
                self.patch.COMMIT_INSTRUCTION,
            ]
        )

        for marker in [
            "SOURCE_FACT",
            "AUTHOR_PROPOSAL",
            "WORLD_MODEL_REQUIRED",
            "EXTERNAL_REFERENCE",
            "OUTLINE_SEARCH_REFERENCE_PROTOCOL",
            "google_search",
            "书内证据",
            "外部参考",
            "推荐选择",
            "路线名",
        ]:
            self.assertIn(marker, combined)

        issue = self.scan.inspect_text(combined, source="unit")
        if issue:
            self.assertNotIn("hardcoded", issue.categories)
            self.assertNotIn("english", issue.categories)
            self.assertNotIn("mojibake", issue.categories)

    def test_outline_prompts_do_not_keep_story_specific_examples(self):
        combined = "\n".join(
            [
                self.patch.OUTLINE_PRODUCTION_CONTROL_PROTOCOL,
                self.patch.OUTLINE_IDEATION_PROTOCOL,
                self.patch.DISCUSS_QUERY,
                self.patch.DISCUSS_INSTRUCTION,
                self.patch.CLASS_1_NAME,
                self.patch.CLASS_2_NAME,
            ]
        )

        for stale_marker in [
            "donk",
            "Major",
            "BLAST",
            "七君",
            "场外军师",
            "群星猎枪篇",
            "Apply this protocol",
            "Your job",
            "Do not",
            "route_name",
            "recommended pick",
        ]:
            self.assertNotIn(stale_marker, combined)

    def test_discuss_tools_normalize_disabled_google_search_entry(self):
        node = {
            "data": {
                "agent_parameters": {
                    "tools": {
                        "type": "constant",
                        "value": [
                            {
                                "type": "api",
                                "enabled": False,
                                "tool_name": "google_search",
                                "provider_name": "langgenius/google/google",
                                "tool_label": "谷歌搜索",
                                "parameters": {"query": {"auto": 1}},
                                "settings": {
                                    "as_agent_tool": {
                                        "value": {"type": "constant", "value": False}
                                    }
                                },
                            }
                        ],
                    }
                }
            }
        }
        provider_tools = [{"operation_id": name, "summary": name, "parameters": []} for name in self.patch.DISCUSS_TOOLS]

        changed = self.patch.set_tools(
            node,
            self.patch.DISCUSS_TOOLS,
            {},
            provider_tools,
            preserve_google_search=True,
        )

        self.assertTrue(changed)
        tools = node["data"]["agent_parameters"]["tools"]["value"]
        self.assertEqual(
            [tool["tool_name"] for tool in tools],
            [*self.patch.DISCUSS_TOOLS, "google_search"],
        )
        self.assertEqual(tools[-1]["provider_name"], "langgenius/google/google")
        self.assertEqual(tools[-1]["type"], "builtin")
        self.assertTrue(tools[-1]["enabled"])
        self.assertTrue(self.patch.google_search_enabled_for_agent(tools[-1]))
        self.assertEqual(tools[-1]["tool_label"], "谷歌搜索")

    def test_discuss_tools_can_inherit_google_search_from_peer_workflow(self):
        node = {
            "data": {
                "agent_parameters": {
                    "tools": {
                        "type": "constant",
                        "value": [],
                    }
                }
            }
        }
        provider_tools = [{"operation_id": name, "summary": name, "parameters": []} for name in self.patch.DISCUSS_TOOLS]
        inherited = {
            "google_search": {
                "type": "api",
                "enabled": True,
                "tool_name": "google_search",
                "provider_name": "langgenius/google/google",
                "tool_label": "谷歌搜索",
                "parameters": {"query": {"auto": 1}},
            }
        }

        self.patch.set_tools(
            node,
            self.patch.DISCUSS_TOOLS,
            inherited,
            provider_tools,
            preserve_google_search=True,
        )

        tools = node["data"]["agent_parameters"]["tools"]["value"]
        self.assertEqual([tool["tool_name"] for tool in tools][-1], "google_search")
        self.assertEqual(tools[-1]["provider_name"], "langgenius/google/google")
        self.assertTrue(self.patch.google_search_enabled_for_agent(tools[-1]))

    def test_outline_agents_enable_thinking_without_clobbering_temperature(self):
        node = {
            "data": {
                "agent_parameters": {
                    "model": {
                        "type": "constant",
                        "value": {"completion_params": {"temperature": 0.2}},
                    }
                }
            }
        }

        changed = self.patch.set_agent_thinking(node, True)

        completion = node["data"]["agent_parameters"]["model"]["value"]["completion_params"]
        self.assertTrue(changed)
        self.assertTrue(completion["thinking"])
        self.assertEqual(completion["temperature"], 0.2)


if __name__ == "__main__":
    unittest.main()
