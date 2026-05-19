import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.tomato_importer import parse_tomato_bulk_export  # noqa: E402


class V66TomatoImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v66_tomato_importer_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write(self, rel_path: str, content: str, encoding: str = "utf-8") -> Path:
        path = self.temp_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return path

    def test_parse_bulk_files_preserves_reading_layout(self):
        source = self.temp_dir / "tomato_export"
        source.mkdir()
        (source / "0000_书籍信息.txt").write_text(
            "书名：测试小说\n作者：测试作者\nbook_id=123456\n",
            encoding="utf-8",
        )
        (source / "0001_第一章_开局.txt").write_text(
            "第一章 开局\n\n"
            "　　陈末站在训练室门口。\n\n"
            "　　“你确定？”\n"
            "　　“确定。”\n\n"
            "　　屏幕亮了起来。\n",
            encoding="utf-8",
        )
        (source / "0002_第二章_回声.txt").write_text(
            "第二章 回声\r\n\r\n"
            "　　第一段保留。\r\n\r\n"
            "　　第二段也保留。\r\n",
            encoding="utf-8",
        )

        parsed = parse_tomato_bulk_export(source, allowed_root=self.temp_dir)

        self.assertEqual(parsed["book_name"], "测试小说")
        self.assertEqual(parsed["metadata"]["author"], "测试作者")
        self.assertEqual(parsed["report"]["chapter_count"], 2)
        first = parsed["chapters"][0]
        self.assertEqual(first["index"], 1)
        self.assertEqual(first["title"], "第一章 开局")
        self.assertTrue(first["target_file"].startswith("0001_"))
        self.assertTrue(first["markdown"].startswith("# 第一章 开局\n\n"))
        self.assertNotIn("第一章 开局\n\n第一章 开局", first["markdown"])
        self.assertIn("　　陈末站在训练室门口。\n\n　　“你确定？”", first["markdown"])
        self.assertIn("　　“确定。”\n\n　　屏幕亮了起来。", first["markdown"])
        self.assertEqual(parsed["chapters"][1]["body"].count("\r"), 0)

    def test_rejects_source_dir_outside_allowed_root(self):
        allowed = self.temp_dir / "allowed"
        outside = self.temp_dir / "outside"
        allowed.mkdir()
        outside.mkdir()
        (outside / "0001_第一章.txt").write_text("第一章\n\n正文", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "escapes allowed_root"):
            parse_tomato_bulk_export(outside, allowed_root=allowed)

    def test_skips_metadata_and_warns_unrecognized_txt(self):
        source = self.temp_dir / "tomato_export"
        source.mkdir()
        (source / "0000_书籍信息.txt").write_text("书名：测试小说", encoding="utf-8")
        (source / "readme.txt").write_text("not a chapter", encoding="utf-8")
        (source / "0001_第一章.txt").write_text("第一章\n\n正文", encoding="utf-8")

        parsed = parse_tomato_bulk_export(source)

        self.assertEqual(parsed["report"]["metadata_file"], "0000_书籍信息.txt")
        self.assertEqual(parsed["report"]["source_files"], ["0001_第一章.txt"])
        self.assertEqual(parsed["report"]["warnings"][0]["code"], "UNRECOGNIZED_TXT_FILE")

    def test_quality_gate_flags_risky_cleaning_results(self):
        source = self.temp_dir / "tomato_export"
        source.mkdir()
        fragmented_body = "\n".join(f"短句{i}" for i in range(1, 25))
        duplicated_body = "\n\n".join(
            [
                "　　重复段落用于制造章节正文 hash 重复，同时保持足够长度，避免被过短章节规则先吞掉主要问题。",
                "　　这里继续扩写一段，让导入质量门槛判断为正常长度的重复内容，而不是下载失败造成的空壳章节。",
                "　　第三段保留自然段落结构，确保这个样本只暴露重复章节内容这一类风险。",
            ]
        )
        (source / "0001_第一章_碎行.txt").write_text(f"第一章 碎行\n\n{fragmented_body}", encoding="utf-8")
        (source / "0002_第二章_重复.txt").write_text(f"第二章 重复\n\n{duplicated_body}", encoding="utf-8")
        (source / "0003_第三章_重复.txt").write_text(f"第三章 重复\n\n{duplicated_body}", encoding="utf-8")

        parsed = parse_tomato_bulk_export(source)

        self.assertFalse(parsed["quality"]["can_confirm"])
        codes = {issue["code"] for issue in parsed["quality"]["issues"]}
        self.assertIn("HIGH_LINE_FRAGMENTATION", codes)
        self.assertIn("DUPLICATE_CHAPTER_CONTENT", codes)


if __name__ == "__main__":
    unittest.main()
