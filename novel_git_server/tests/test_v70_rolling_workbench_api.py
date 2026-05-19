import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


def card(number: int, title: str) -> str:
    return (
        f"## \u7ae0\u8282\u5361 {number}: {title}\n\n"
        "- chapter_goal: goal\n"
        "- entry_scene: entry\n"
        "- conflict_or_obstacle: obstacle\n"
        "- payoff: payoff\n"
        "- state_change: state\n"
        "- foreshadowing_action: foreshadow\n"
        "- ending_hook: hook\n"
        "- evidence_mode: AUTHOR_PROPOSAL\n"
    )


def bold_ch_card(number: int, title: str) -> str:
    return (
        f"### CH{number} — {title}\n\n"
        f"**章节目标**：目标{number}\n\n"
        f"**入场场景**：入场{number}\n\n"
        f"**冲突/阻碍**：阻碍{number}\n\n"
        f"**当章兑现**：兑现{number}\n\n"
        f"**状态变化**：状态{number}\n\n"
        f"**伏笔动作**：伏笔{number}\n\n"
        f"**结尾钩子**：尾钩{number}\n\n"
        f"**约束引用**：约束{number}\n\n"
        "**证据模式**：AUTHOR_PROPOSAL\n"
    )


class V70RollingWorkbenchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v70_rolling_api_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _init_book(self, book_name: str = "v70_rolling") -> tuple[str, Path]:
        response = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        book_id = body["book_id"]
        return book_id, self.temp_dir / book_id

    def test_state_projects_written_pending_selected_without_mutating_files(self):
        book_id, book_dir = self._init_book("v70_projection")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(1, 6))
        draft_text = (
            "# draft\n\n"
            "## \u7b2c1\u7ae0 title-1\nbody\n"
            "## \u7b2c2\u7ae0 title-2\nbody\n"
            "## \u7b2c3\u7ae0 title-3\nbody\n"
        )
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        (book_dir / "chapter_draft.md").write_text(draft_text, encoding="utf-8")

        response = self.client.get("/api/rolling/state", query_string={"book_id": book_id})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        state = body["workbench_state"]
        self.assertEqual(state["next_action"], "continue_existing_cards")
        self.assertFalse(state["requiresPrompt"])
        self.assertEqual(state["executionKind"], "direct_job")
        self.assertEqual(state["written_chapter_numbers"], [])
        self.assertEqual(state["accepted_chapter_numbers"], [])
        self.assertEqual(state["pending_review_chapter_numbers"], [1, 2, 3])
        self.assertEqual(state["pending_card_numbers"], [4, 5])
        self.assertEqual(state["selected_card_numbers"], [4, 5])
        self.assertEqual([card["status"] for card in state["outline_card_states"]], ["pending_review", "pending_review", "pending_review", "selected", "selected"])
        self.assertEqual(state["outline_card_states"][3]["title"], "title-4")
        self.assertEqual(state["outline_diagnostics"]["outline_card_count"], 5)
        self.assertEqual(state["outline_diagnostics"]["executable_card_count"], 5)
        self.assertFalse(state["outline_diagnostics"]["detected_but_unparsed"])
        self.assertTrue(state["replenishment_needed_after_selected_batch"])
        self.assertTrue(state["source_files"]["chapter_outline"]["exists"])
        self.assertTrue(state["source_files"]["chapter_draft"]["exists"])
        self.assertTrue(state["no_prose_boundary"]["continuation_agent_remains_only_chapter_draft_writer"])
        self.assertFalse(state["no_prose_boundary"]["state_mutates_chapter_outline"])
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)

    def test_state_projects_current_ch_heading_outline_card_titles(self):
        book_id, book_dir = self._init_book("v70_ch_heading_projection")
        outline_text = (
            "# 逐章大纲\n\n"
            + "\n---\n\n".join(
                bold_ch_card(number, title)
                for number, title in (
                    (153, "伊甸园的钟"),
                    (154, "1200万的影子"),
                    (155, "Veto桌上的神"),
                )
            )
        )
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        draft_path = book_dir / "chapter_draft.md"
        if draft_path.exists():
            draft_path.unlink()

        response = self.client.get("/api/rolling/state", query_string={"book_id": book_id})

        self.assertEqual(response.status_code, 200)
        state = response.get_json()["workbench_state"]
        self.assertEqual(state["next_action"], "continue_existing_cards")
        self.assertEqual(state["selected_card_numbers"], [153, 154, 155])
        self.assertEqual(
            [(card["number"], card["title"], card["status"]) for card in state["outline_card_states"]],
            [
                (153, "伊甸园的钟", "selected"),
                (154, "1200万的影子", "selected"),
                (155, "Veto桌上的神", "selected"),
            ],
        )
        self.assertEqual(state["outline_diagnostics"]["outline_card_count"], 3)
        self.assertEqual(state["outline_diagnostics"]["executable_card_count"], 3)
        self.assertFalse(state["outline_diagnostics"]["detected_but_unparsed"])
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)

    def test_state_missing_draft_uses_virtual_empty_cursor_without_creating_file(self):
        book_id, book_dir = self._init_book("v70_missing_draft")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(1, 4))
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        draft_path = book_dir / "chapter_draft.md"
        if draft_path.exists():
            draft_path.unlink()

        response = self.client.get("/api/rolling/state", query_string={"book_id": book_id, "batch_size": 9})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        state = body["workbench_state"]
        self.assertEqual(state["batch_size"], 3)
        self.assertEqual(state["written_chapter_numbers"], [])
        self.assertEqual(state["selected_card_numbers"], [1, 2, 3])
        self.assertFalse(state["source_files"]["chapter_draft"]["exists"])
        self.assertFalse((book_dir / "chapter_draft.md").exists())
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)

    def test_state_depleted_cards_requests_replenishment_without_clearing_outline(self):
        book_id, book_dir = self._init_book("v70_depleted")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(1, 4))
        draft_text = "# draft\n\n" + "\n".join(f"## \u7b2c{i}\u7ae0 title-{i}\nbody\n" for i in range(1, 4))
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        (book_dir / "chapter_draft.md").write_text(draft_text, encoding="utf-8")

        response = self.client.get("/api/rolling/state", query_string={"book_id": book_id})

        self.assertEqual(response.status_code, 200)
        state = response.get_json()["workbench_state"]
        self.assertEqual(state["next_action"], "replenish_outline")
        self.assertEqual(state["selected_card_numbers"], [])
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)

    def test_state_distinguishes_accepted_pending_review_and_selected_cards(self):
        book_id, book_dir = self._init_book("v70_accepted_pending_projection")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(153, 159))
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        for number in range(153, 156):
            (book_dir / "chapters" / f"{number:04d}_第{number}章_title-{number}.md").write_text(
                f"## 第{number}章 title-{number}\naccepted-{number}\n",
                encoding="utf-8",
            )
        (book_dir / "chapter_draft.md").write_text(
            "# 续写草稿\n\n## 第156章 title-156\npending-review-156\n",
            encoding="utf-8",
        )

        response = self.client.get("/api/rolling/state", query_string={"book_id": book_id})

        self.assertEqual(response.status_code, 200)
        state = response.get_json()["workbench_state"]
        self.assertEqual(state["accepted_chapter_numbers"], [153, 154, 155])
        self.assertEqual(state["pending_review_chapter_numbers"], [156])
        self.assertEqual(state["selected_card_numbers"], [157, 158])
        self.assertEqual(
            [card["status"] for card in state["outline_card_states"]],
            ["written", "written", "written", "pending_review", "selected", "selected"],
        )
        self.assertTrue(state["source_files"]["chapters"]["exists"])
        self.assertEqual(state["source_files"]["chapters"]["kind"], "directory")
        self.assertEqual(state["source_files"]["chapters"]["entry_count"], 3)

    def test_continuation_payload_routes_existing_cards_without_prose_or_outline_mutation(self):
        book_id, book_dir = self._init_book("v70_continuation_payload")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(1, 5))
        draft_text = (
            "# draft\n\n"
            "## \u7b2c1\u7ae0 title-1\nUNIQUE_DRAFT_PROSE_1\n"
        )
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        (book_dir / "chapter_draft.md").write_text(draft_text, encoding="utf-8")

        response = self.client.post(
            "/api/rolling/continuation_payload",
            json={"book_id": book_id, "batch_size": 3},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        body_text = repr(body)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["route_agent_key"], "continuation_agent")
        self.assertEqual(body["target_file"], "chapter_draft.md")
        self.assertEqual(body["file_type"], "chapter")
        self.assertEqual(body["write_scope"], "active_file_strict")
        self.assertEqual(body["chapter_number"], 2)
        self.assertEqual(body["workbench_state"]["selected_card_numbers"], [2, 3, 4])
        brief = body["author_writing_brief"]
        self.assertEqual(brief["brief_type"], "rolling_author_writing_brief")
        self.assertEqual(brief["route_agent_key"], "continuation_agent")
        self.assertEqual(brief["target_file"], "chapter_draft.md")
        self.assertEqual(brief["batch"]["selected_card_numbers"], [2, 3, 4])
        self.assertEqual(brief["progress_cursor"]["pending_review_chapter_numbers"], [1])
        self.assertEqual([item["number"] for item in brief["chapter_cards"]], [2, 3, 4])
        self.assertEqual(brief["chapter_cards"][0]["goal"], "goal")
        self.assertEqual(brief["chapter_cards"][0]["conflict"], "obstacle")
        self.assertIn("selected_card_numbers", brief["writing_contract"]["what_to_write"])
        self.assertIn("chapter_draft.md", brief["writing_contract"]["where_to_write"])
        self.assertTrue(any(source["name"] == "chapter_outline.md" for source in brief["truth_sources"]))
        self.assertFalse(brief["no_prose_boundary"]["brief_contains_generated_prose"])
        self.assertFalse(brief["no_prose_boundary"]["brief_reads_chapter_draft_text"])
        self.assertTrue(brief["no_prose_boundary"]["continuation_agent_remains_only_chapter_draft_writer"])
        self.assertIn("CHAPTER_CONTEXT_PACK_PROTOCOL", body["intent"])
        self.assertIn("chapter_context_pack JSON", body["intent"])
        self.assertIn("selected_card_numbers", body["intent"])
        self.assertFalse(body["no_prose_boundary"]["payload_contains_generated_prose"])
        self.assertTrue(body["no_prose_boundary"]["continuation_agent_remains_only_chapter_draft_writer"])
        self.assertNotIn("UNIQUE_DRAFT_PROSE_1", body_text)
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)

    def test_continuation_payload_rejects_depleted_cards(self):
        book_id, book_dir = self._init_book("v70_continuation_not_ready")
        outline_text = "# outline\n\n" + "\n".join(card(i, f"title-{i}") for i in range(1, 3))
        draft_text = "# draft\n\n" + "\n".join(f"## \u7b2c{i}\u7ae0 title-{i}\nbody\n" for i in range(1, 3))
        (book_dir / "chapter_outline.md").write_text(outline_text, encoding="utf-8")
        (book_dir / "chapter_draft.md").write_text(draft_text, encoding="utf-8")

        response = self.client.post(
            "/api/rolling/continuation_payload",
            json={"book_id": book_id, "batch_size": 3},
        )

        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertEqual(body["code"], "ROLLING_NOT_READY")
        self.assertEqual(body["next_action"], "replenish_outline")
        self.assertEqual(body["workbench_state"]["selected_card_numbers"], [])
        self.assertEqual((book_dir / "chapter_outline.md").read_text(encoding="utf-8"), outline_text)


if __name__ == "__main__":
    unittest.main()
