import importlib.util
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT_DIR / "scripts" / "patch_world_model_agent.py"


def load_patch_module():
    spec = importlib.util.spec_from_file_location("patch_world_model_agent", PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {PATCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V70WorldConstraintLifecyclePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = load_patch_module()

    def test_world_prompts_expose_constraint_lifecycle_protocol(self):
        combined = "\n".join(
            [
                self.patch.SUMMARY_DISTILLATION_PROTOCOL,
                self.patch.CONSTRAINT_LIFECYCLE_PROTOCOL,
                self.patch.READ_AGENT_PROMPT,
                self.patch.ONLINE_AGENT_PROMPT,
            ]
        )

        for marker in [
            "CONSTRAINT_LIFECYCLE_PROTOCOL",
            "Constraint Lifecycle Ledger",
            "lifecycle_status",
            "applicability_scope",
            "current-active",
            "historical-only",
            "retired",
            "overridden",
            "disabled",
            "disabled-in-current-scope",
            "conditional",
            "inherited-residue",
            "unresolved",
            "legacy-unclassified",
            "source-evidence-window",
            "lifecycle_change",
            "不得被下游当成 current-active 使用",
        ]:
            self.assertIn(marker, combined)

    def test_summary_alignment_requires_lifecycle_changes_instead_of_flat_downgrade(self):
        prompt = self.patch.SUMMARY_DISTILLATION_PROTOCOL

        for marker in [
            "summary.md 最新段落优先",
            "lifecycle_change",
            "historical-only",
            "retired",
            "overridden",
            "disabled",
            "disabled-in-current-scope",
            "inherited-residue",
            "unresolved",
            "applicability_scope",
        ]:
            self.assertIn(marker, prompt)

        self.assertNotIn("旧口径必须降级为\"已回收 / 历史压力源 / 待复核\"", prompt)

    def test_expected_prompt_markers_require_lifecycle_for_post_init_world_agents(self):
        for title in ("READ AGENT", "ONLINE_AGENT"):
            markers = self.patch.EXPECTED_PROMPT_MARKERS[title]
            for marker in [
                "CONSTRAINT_LIFECYCLE_PROTOCOL",
                "Constraint Lifecycle Ledger",
                "current-active",
                "historical-only",
                "disabled-in-current-scope",
                "legacy-unclassified",
                "applicability_scope",
                "不得被下游当成 current-active 使用",
            ]:
                self.assertIn(marker, markers)

    def test_read_and_online_prompts_keep_post_init_write_scope(self):
        read_prompt = self.patch.READ_AGENT_PROMPT
        online_prompt = self.patch.ONLINE_AGENT_PROMPT

        for prompt in (read_prompt, online_prompt):
            self.assertIn("世界模型创作约束引擎", prompt)
            self.assertIn("写入只允许进入 world_model.md、status_card.md、domain_rules.md", prompt)
            self.assertIn("draft_append_markdown_section", prompt)
            self.assertIn("draft_replace_markdown_section", prompt)

    def test_world_init_agent_is_retired_but_read_and_online_remain_post_init(self):
        init_prompt = self.patch.INIT_AGENT_PROMPT
        combined_post_init = f"{self.patch.READ_AGENT_PROMPT}\n{self.patch.ONLINE_AGENT_PROMPT}"

        for marker in [
            "初始化职责已退役",
            "/api/world/init_batch_pipeline",
            "world_model.md 与 status_card.md 的首次生成由后端批处理管线负责",
            "Dify 世界模型工作流只做初始化后阶段",
            "不得调用 draft_append_markdown_section",
            "不得调用 draft_replace_markdown_section",
        ]:
            self.assertIn(marker, init_prompt)

        for marker in [
            "你是作者升级通道，不是默认初始化通道",
            "后端批处理管线已生成的世界模型主轴",
            "现实考据与设定校准读写智能体",
            "写入只允许进入 world_model.md、status_card.md、domain_rules.md",
            "explicit_user_write",
        ]:
            self.assertIn(marker, combined_post_init)

    def test_world_queries_guide_initialization_to_backend_without_disabling_post_init_agents(self):
        init_query = self.patch.AGENT_QUERIES["INIT_AGENT"]
        read_query = self.patch.AGENT_QUERIES["READ AGENT"]
        online_query = self.patch.AGENT_QUERIES["ONLINE_AGENT"]

        self.assertIn("/api/world/init_batch_pipeline", init_query)
        self.assertIn("不得调用写入工具", init_query)
        self.assertIn("作者升级深读智能体", read_query)
        self.assertIn("后端批处理管线产物不合适时接手", read_query)
        self.assertIn("现实考据智能体", online_query)


if __name__ == "__main__":
    unittest.main()
