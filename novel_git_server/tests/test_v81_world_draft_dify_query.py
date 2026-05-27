import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents.world_draft_dify import _build_dify_query  # noqa: E402


class V81WorldDraftDifyQueryTests(unittest.TestCase):
    def test_outline_landing_button_intent_is_rewritten_to_commit_command(self) -> None:
        query = _build_dify_query(
            "# 总纲\n",
            {
                "intent": (
                    "【大纲落档按钮请求】\n\n"
                    "这是作者点击落档按钮触发的明确写入请求。\n"
                    "需要落档的大纲助手回复如下：\n"
                    "我建议先讨论三条路线。\n\n"
                    "目标文件：master_outline.md"
                ),
                "active_file": "master_outline.md",
            },
        )

        self.assertIn("请立即为 master_outline.md 生成大纲草稿并写入", query)
        self.assertIn("不是讨论", query)
        self.assertIn("draft_replace_markdown_section", query)
        self.assertNotIn("我建议先讨论三条路线", query)


if __name__ == "__main__":
    unittest.main()
