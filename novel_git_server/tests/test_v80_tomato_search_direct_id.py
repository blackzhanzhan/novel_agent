import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils import tomato_search  # noqa: E402


class V80TomatoSearchDirectIdTests(unittest.TestCase):
    def test_extract_initial_state_handles_inner_semicolon_brace_text(self) -> None:
        html = (
            '<script>window.__INITIAL_STATE__='
            '{"page":{"bookName":"兽人规则","abstract":"内部文本 }; 不应截断",'
            '"itemIds":["1","2"]},"search":{}};'
            '</script>'
        )

        state = tomato_search._extract_initial_state(html, context="unit")

        self.assertEqual(state["page"]["bookName"], "兽人规则")
        self.assertEqual(state["page"]["itemIds"], ["1", "2"])

    def test_numeric_book_id_returns_book_info_result(self) -> None:
        with patch("utils.tomato_search.get_book_info") as get_book_info:
            get_book_info.return_value = {
                "book_id": "7539874853881383998",
                "book_name": "兽人规则",
                "author": "梦里的豹子",
                "abstract": "规则怪谈故事。",
                "word_count": 0,
                "chapter_count": 23,
            }

            results = tomato_search.search_novels("7539874853881383998", count=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["book_id"], "7539874853881383998")
        self.assertEqual(results[0]["book_name"], "兽人规则")
        self.assertEqual(results[0]["chapter_count"], 23)

    def test_fanqie_page_url_returns_book_info_result(self) -> None:
        with patch("utils.tomato_search.get_book_info") as get_book_info:
            get_book_info.return_value = {
                "book_id": "7539874853881383998",
                "book_name": "兽人规则",
                "author": "梦里的豹子",
                "abstract": "",
                "word_count": 0,
                "chapter_count": 23,
            }

            results = tomato_search.search_novels(
                "https://fanqienovel.com/page/7539874853881383998",
                count=5,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["book_id"], "7539874853881383998")
        get_book_info.assert_called_once_with("7539874853881383998")


if __name__ == "__main__":
    unittest.main()
