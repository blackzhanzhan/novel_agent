import importlib.util
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT_DIR / "scripts" / "patch_world_model_agent.py"
SCAN_PATH = ROOT_DIR / "scripts" / "scan_dify_prompt_hygiene.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V75WorldPromptCnGenericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = load_module("patch_world_model_agent_v75", PATCH_PATH)
        cls.scan = load_module("scan_dify_prompt_hygiene_v75", SCAN_PATH)

    def test_world_prompts_are_chinese_generic_under_prompt_scanner(self):
        combined = "\n".join(
            [
                self.patch.BOUNDED_READ_GUARD,
                self.patch.SUMMARY_DISTILLATION_PROTOCOL,
                self.patch.CONSTRAINT_LIFECYCLE_PROTOCOL,
                self.patch.EXPLICIT_WRITE_INTENT_PROTOCOL,
                self.patch.TOOL_PARAMETER_PROTOCOL,
                self.patch.INIT_AGENT_PROMPT,
                self.patch.READ_AGENT_PROMPT,
                self.patch.ONLINE_AGENT_PROMPT,
                self.patch.INTERNAL_ROUTER_CLASS,
                self.patch.EXTERNAL_ROUTER_CLASS,
                *self.patch.AGENT_QUERIES.values(),
            ]
        )

        issue = self.scan.inspect_text(combined, source="unit")
        if issue:
            self.assertNotIn("hardcoded", issue.categories)
            self.assertNotIn("english", issue.categories)
            self.assertNotIn("mojibake", issue.categories)

        for stale_marker in [
            "陈末",
            "Major",
            "donk",
            "BLAST",
            "Apply this protocol",
            "Your job",
            "Do not",
            "must not",
            "You are",
            "only current-active",
        ]:
            self.assertNotIn(stale_marker, combined)

        source = PATCH_PATH.read_text(encoding="utf-8")
        self.assertNotIn("陈末", source)
        self.assertNotIn("Major", source)

    def test_router_class_cleanup_removes_story_specific_examples(self):
        graph = {
            "nodes": [
                {
                    "data": {
                        "classes": [
                            {"name": "核心关键词：解析原文、读取章节、分析剧情。陈末在原文里干了什么。"},
                            {"name": "核心关键词：联网搜索、考据现实、查询 Major 细节、地理环境。"},
                        ]
                    }
                }
            ]
        }

        changed = self.patch.patch_router_classes(graph)
        class_names = [item["name"] for item in graph["nodes"][0]["data"]["classes"]]

        self.assertTrue(changed)
        self.assertEqual(class_names, [self.patch.INTERNAL_ROUTER_CLASS, self.patch.EXTERNAL_ROUTER_CLASS])
        self.assertNotIn("陈末", "\n".join(class_names))
        self.assertNotIn("Major", "\n".join(class_names))

    def test_historical_workflow_cleanup_only_touches_prompt_surfaces(self):
        graph = {
            "nodes": [
                {
                    "data": {
                        "type": "start",
                        "variables": [
                            {"variable": "book_name"},
                        ],
                    }
                },
                {
                    "data": {
                        "type": "if-else",
                        "classes": [
                            {"name": "核心关键词：联网搜索、考据现实、查询 Major 细节、地理环境。"},
                        ],
                    }
                },
            ],
            "edges": [],
        }

        changed = self.patch.patch_graph(graph, full_runtime_patch=False)
        variables = graph["nodes"][0]["data"]["variables"]

        self.assertTrue(changed)
        self.assertEqual([item["variable"] for item in variables], ["book_name"])
        self.assertEqual(graph["nodes"][1]["data"]["classes"][0]["name"], self.patch.EXTERNAL_ROUTER_CLASS)


if __name__ == "__main__":
    unittest.main()
