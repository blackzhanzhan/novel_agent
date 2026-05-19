import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.markdown_sections import (  # noqa: E402
    MarkdownSectionAmbiguousError,
    append_under_markdown_section,
    build_markdown_outline,
    extract_markdown_section,
    find_markdown_section,
    replay_markdown_patch,
    replace_markdown_section,
)


class V57MarkdownSectionsTests(unittest.TestCase):
    def test_outline_skips_yaml_frontmatter_and_fenced_headings(self):
        markdown = (
            "---\n"
            'title: "# not a heading"\n'
            "book: donk\n"
            "---\n"
            "# World\n"
            "```md\n"
            "## Fake Heading\n"
            "```\n"
            "## Rules\n"
            "content\n"
        )

        outline = build_markdown_outline(markdown)

        self.assertEqual([item["title"] for item in outline], ["World", "Rules"])
        self.assertEqual(outline[0]["heading_line"], 5)
        self.assertEqual(outline[1]["heading_line"], 9)

    def test_extract_section_marks_empty_content_explicitly(self):
        markdown = "# Root\n## A\n## B\nbody\n"

        section = extract_markdown_section(markdown, ["Root", "A"])

        self.assertEqual(section["content"], "")
        self.assertEqual(section["content_length"], 0)
        self.assertEqual(section["heading_line"], 2)
        self.assertEqual(section["end_line"], 2)

    def test_duplicate_sibling_titles_require_canonical_path(self):
        markdown = "# Root\n## Rule\nalpha\n## Rule\nbeta\n"

        with self.assertRaises(MarkdownSectionAmbiguousError):
            find_markdown_section(markdown, ["Root", "Rule"])

        second = extract_markdown_section(markdown, ["Root", "Rule [2]"])
        self.assertEqual(second["content"], "beta\n")

    def test_append_under_section_inserts_after_last_descendant_before_next_sibling(self):
        markdown = (
            "# Root\n"
            "## Characters\n"
            "### Alice\n"
            "old-a\n"
            "### Bob\n"
            "old-b\n"
            "## Rules\n"
            "stay\n"
        )

        updated = append_under_markdown_section(
            markdown,
            ["Root", "Characters"],
            "### Carol\nold-c\n",
        )

        self.assertIn("### Bob\nold-b\n### Carol\nold-c\n## Rules", updated)
        self.assertNotIn("### Bob\nold-b\n## Rules\n### Carol", updated)

    def test_replace_section_only_replaces_target_block(self):
        markdown = (
            "# Root\n"
            "## Characters\n"
            "### Alice\n"
            "old-a\n"
            "## Rules\n"
            "stay\n"
        )

        updated = replace_markdown_section(
            markdown,
            ["Root", "Characters", "Alice"],
            "### Alice\nnew-a\n",
        )

        self.assertIn("### Alice\nnew-a\n", updated)
        self.assertIn("## Rules\nstay\n", updated)
        self.assertNotIn("old-a", updated)

    def test_replay_patch_reapplies_on_latest_markdown_after_concurrent_change(self):
        base_markdown = (
            "# Root\n"
            "## Characters\n"
            "### Alice\n"
            "old-a\n"
            "## Rules\n"
            "stay\n"
        )
        latest_markdown = (
            "# Root\n"
            "## Characters\n"
            "### Alice\n"
            "old-a\n"
            "### Bob\n"
            "old-b\n"
            "## Rules\n"
            "stay\n"
        )
        patch = {
            "op": "append_under_section",
            "section_path": ["Root", "Characters"],
            "content": "### Carol\nold-c\n",
        }

        rebased = replay_markdown_patch(latest_markdown, patch)

        self.assertIn("### Bob\nold-b\n### Carol\nold-c\n## Rules", rebased)
        self.assertNotEqual(rebased, base_markdown)


if __name__ == "__main__":
    unittest.main()
