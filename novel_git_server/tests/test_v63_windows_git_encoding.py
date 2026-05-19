import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents import world_draft  # noqa: E402
from utils.git_utils import run_git  # noqa: E402


class V63WindowsGitEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = tmp_root / f"v63_windows_git_encoding_{uuid.uuid4().hex}"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self._git("init")
        self._git("config", "user.name", "LoreGit Test")
        self._git("config", "user.email", "loregit-test@example.local")

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "gc", "--prune=now"],
            cwd=self.repo_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def test_run_git_decodes_utf8_markdown_on_windows(self):
        content = "# 篇章大纲\n\n第六世回潮——donk 恢复灵性的条件。\n"
        (self.repo_dir / "arc_outline.md").write_text(content, encoding="utf-8")
        self._git("add", "arc_outline.md")
        self._git("commit", "-m", "init utf8 markdown")

        result = run_git(str(self.repo_dir), ["show", "HEAD:arc_outline.md"])

        self.assertIsInstance(result.stdout, str)
        self.assertIn("第六世回潮", result.stdout)
        self.assertIn("——", result.stdout)

    def test_draft_snapshot_never_hashes_none_content(self):
        content = "# 状态卡片\n\n恢复灵性：知道。\n"
        (self.repo_dir / "status_card.md").write_text(content, encoding="utf-8")
        self._git("add", "status_card.md")
        self._git("commit", "-m", "init status")
        self._git("checkout", "-b", world_draft.DRAFT_BRANCH_NAME)

        snapshot = world_draft._draft_file_snapshot(str(self.repo_dir), "status_card.md")

        self.assertTrue(snapshot["exists"])
        self.assertIsInstance(snapshot["content"], str)
        self.assertIn("恢复灵性", snapshot["content"])
        self.assertEqual(snapshot["etag"], world_draft._compute_text_etag(snapshot["content"]))


if __name__ == "__main__":
    unittest.main()
