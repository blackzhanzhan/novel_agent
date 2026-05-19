import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as gs  # noqa: E402


class V67DomainRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / ".tmp_tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f"v67_domain_rules_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _git(self, repo_dir: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _init_book(self, book_name: str) -> tuple[str, Path]:
        resp = self.client.post("/books/init", json={"book_name": book_name})
        self.assertEqual(resp.status_code, 200)
        book_id = resp.get_json()["book_id"]
        return book_id, self.temp_dir / book_id

    def test_book_init_creates_and_tracks_domain_rules(self):
        _book_id, repo_dir = self._init_book("v67_domain_layout")

        domain_rules = repo_dir / "domain_rules.md"
        self.assertTrue(domain_rules.exists())
        content = domain_rules.read_text(encoding="utf-8")
        self.assertIn("不要在代码中硬编码题材规则", content)
        self.assertIn("domain-rule 示例", content)

        tracked = self._git(repo_dir, "ls-files", "--", "domain_rules.md")
        self.assertEqual(tracked, "domain_rules.md")

    def test_validate_domain_facts_allows_empty_rules(self):
        book_id, repo_dir = self._init_book("v67_empty_rules")
        (repo_dir / "chapter_draft.md").write_text("## 第一章\n这里没有沉淀任何领域规则。\n", encoding="utf-8")

        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["rule_count"], 0)
        self.assertEqual(body["violation_count"], 0)

    def test_context_forbidden_terms_are_generated_rule_driven_not_hardcoded(self):
        book_id, repo_dir = self._init_book("v67_context_rule")
        (repo_dir / "domain_rules.md").write_text(
            """# 领域规则

```domain-rule
{
  "id": "fictional_scene_term_conflict",
  "type": "context_forbidden_terms",
  "scope": "chapter",
  "context_terms": ["荒漠"],
  "forbidden_terms": ["沼泽门"],
  "severity": "error",
  "message": "荒漠场景不能使用沼泽门术语"
}
```
""",
            encoding="utf-8",
        )
        (repo_dir / "chapter_draft.md").write_text("## 第一章\n荒漠里出现沼泽门。\n", encoding="utf-8")

        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["rule_count"], 1)
        self.assertEqual(body["violation_count"], 1)
        self.assertEqual(body["violations"][0]["code"], "CONTEXT_FORBIDDEN_TERM")
        self.assertEqual(body["violations"][0]["rule_id"], "fictional_scene_term_conflict")

    def test_ordered_patterns_forbidden_catches_generated_sequence_rule(self):
        book_id, repo_dir = self._init_book("v67_ordered_rule")
        (repo_dir / "domain_rules.md").write_text(
            """# 领域规则

```domain-rule
{
  "id": "score_sequence_conflict",
  "type": "ordered_patterns_forbidden",
  "scope": "chapter",
  "patterns": ["二比零", "第三局"],
  "message": "二比零后不应继续出现第三局"
}
```
""",
            encoding="utf-8",
        )
        (repo_dir / "chapter_draft.md").write_text("## 第一章\n比赛已经二比零结束，众人却又走向第三局。\n", encoding="utf-8")

        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["violations"][0]["code"], "ORDERED_PATTERNS_FORBIDDEN")

    def test_context_rules_fail_closed_on_prose_context_and_regex_literals(self):
        book_id, repo_dir = self._init_book("v67_invalid_generated_rule")
        (repo_dir / "domain_rules.md").write_text(
            """# 领域规则

```domain-rule
{
  "id": "generated_rule_with_prose_context",
  "type": "context_forbidden_terms",
  "scope": "line",
  "context": "T方进攻方回合，非CT防守方",
  "forbidden_terms": ["购买USP"]
}
```

```domain-rule
{
  "id": "generated_rule_with_regex_literal",
  "type": "context_forbidden_terms",
  "scope": "line",
  "context_terms": ["Mirage"],
  "forbidden_terms": ["Mirage.*香蕉道"]
}
```
""",
            encoding="utf-8",
        )
        (repo_dir / "chapter_draft.md").write_text("## 第一章\nSpirit作为T方进入手枪局，donk购买USP。\n", encoding="utf-8")

        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["rule_count"], 2)
        self.assertEqual(body["violation_count"], 2)
        self.assertEqual({row["code"] for row in body["violations"]}, {"INVALID_RULE"})

    def test_cs_domain_rules_catch_current_book_regressions_without_hardcoding(self):
        book_id, repo_dir = self._init_book("v67_cs_domain_rule_examples")
        (repo_dir / "domain_rules.md").write_text(
            """# 领域规则

```domain-rule
[
  {
    "id": "t_side_usp_hard_ban",
    "type": "context_forbidden_terms",
    "scope": "line",
    "context_terms": ["作为T方"],
    "forbidden_terms": ["购买USP", "使用USP", "USP-S"],
    "severity": "error"
  },
  {
    "id": "mirage_banana_term_hard_ban",
    "type": "regex_forbidden",
    "scope": "line",
    "patterns": ["Mirage[^\\n。！？]*香蕉道", "香蕉道[^\\n。！？]*Mirage"],
    "severity": "error"
  }
]
```
""",
            encoding="utf-8",
        )
        (repo_dir / "chapter_draft.md").write_text(
            "## 第一章\nSpirit作为T方进入手枪局，donk购买USP，准备冲A。\n"
            "## 第二章\nMirage地图上，NiKo在香蕉道近点和拱门完成联动。\n",
            encoding="utf-8",
        )

        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["rule_count"], 2)
        self.assertEqual(body["violation_count"], 2)
        self.assertEqual({row["rule_id"] for row in body["violations"]}, {"t_side_usp_hard_ban", "mirage_banana_term_hard_ban"})

        (repo_dir / "chapter_draft.md").write_text(
            "## 第一章\nInferno地图上，Spirit作为CT方防守香蕉道，USP-S挂在腿侧。\n",
            encoding="utf-8",
        )
        resp = self.client.post("/tools/validate_domain_facts", json={"book_id": book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["violation_count"], 0)

    def test_validate_domain_facts_accepts_inline_markdown_for_rule_smoke_tests(self):
        book_id, repo_dir = self._init_book("v67_inline_smoke")
        (repo_dir / "domain_rules.md").write_text(
            """# 领域规则

```domain-rule
{
  "id": "mirage_banana_term_hard_ban",
  "type": "regex_forbidden",
  "scope": "line",
  "patterns": ["Mirage[^\\n。！？]*香蕉道", "香蕉道[^\\n。！？]*Mirage"],
  "severity": "error"
}
```
""",
            encoding="utf-8",
        )

        resp = self.client.post(
            "/tools/validate_domain_facts",
            json={
                "book_id": book_id,
                "markdown": "## 第一章\nMirage地图上，NiKo在香蕉道近点和拱门完成联动。\n",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["source"], "inline")
        self.assertEqual(body["file_name"], "__inline_markdown__")
        self.assertFalse(body["ok"])
        self.assertEqual(body["violations"][0]["rule_id"], "mirage_banana_term_hard_ban")

        resp = self.client.post(
            "/tools/validate_domain_facts",
            json={
                "book_id": book_id,
                "markdown": "## 第一章\nInferno地图上，NiKo在香蕉道近点防守。\n",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])

    def test_validate_domain_facts_rejects_path_traversal(self):
        book_id, repo_dir = self._init_book("v67_path_guard")
        (repo_dir / "chapter_draft.md").write_text("## 第一章\n路径保护用草稿。\n", encoding="utf-8")

        resp = self.client.post(
            "/tools/validate_domain_facts",
            json={"book_id": book_id, "file_name": "../chapter_draft.md"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

        resp = self.client.post(
            "/tools/validate_domain_facts",
            json={"book_id": book_id, "rules_file": "../domain_rules.md"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_PAYLOAD")

    def test_dify_openapi_persists_domain_rule_and_exact_replace_tools(self):
        openapi = json.loads((ROOT_DIR / "docs" / "openapi_v3_5_1_draft_min.json").read_text(encoding="utf-8"))
        self.assertIn("/tools/validate_domain_facts", openapi["paths"])
        self.assertIn("/api/draft/replace_text", openapi["paths"])

        replace_schema = openapi["paths"]["/api/draft/replace_text"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        self.assertIn("domain_rules.md", replace_schema["properties"]["file_name"]["enum"])

        validate_schema = openapi["paths"]["/tools/validate_domain_facts"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(validate_schema["properties"]["rules_file"]["default"], "domain_rules.md")


if __name__ == "__main__":
    unittest.main()
