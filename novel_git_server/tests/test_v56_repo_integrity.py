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


class V56RepoIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT_DIR / '.tmp_tests'
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tmp_root / f'v56_repo_integrity_{uuid.uuid4().hex}'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app = gs.create_app(storage_root=str(self.temp_dir))
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _git(self, repo_dir: Path, *args: str) -> str:
        return subprocess.run(
            ['git', *args],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _init_book(self, *, book_name: str) -> tuple[str, Path]:
        resp = self.client.post('/books/init', json={'book_name': book_name})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        book_id = body['book_id']
        return book_id, self.temp_dir / book_id

    def _reset_to_metadata_only_commit(self, repo_dir: Path) -> str:
        commits = self._git(repo_dir, 'rev-list', '--reverse', 'HEAD').splitlines()
        self.assertGreaterEqual(len(commits), 2)
        target = commits[0]
        self._git(repo_dir, 'reset', '--hard', target)
        return target

    def test_get_file_virtualizes_missing_core_after_reset(self):
        book_id, repo_dir = self._init_book(book_name='v56_virtual_core')
        self._reset_to_metadata_only_commit(repo_dir)

        resp = self.client.get(
            '/books/get_file',
            query_string={'book_id': book_id, 'file_name': 'status_card.md'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body['exists'])
        self.assertTrue(body['virtual'])
        self.assertEqual(body['content'], '')
        self.assertTrue(body['integrity']['needs_repair'])
        self.assertIn('status_card.md', body['integrity']['missing_core_files'])

    def test_list_hot_files_marks_virtual_core_after_reset(self):
        book_id, repo_dir = self._init_book(book_name='v56_hot_files')
        self._reset_to_metadata_only_commit(repo_dir)

        resp = self.client.get('/books/list_hot_files', query_string={'book_id': book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        world_row = next((row for row in body['files'] if row['file_name'] == 'world_model.md'), None)
        self.assertIsNotNone(world_row)
        assert world_row is not None
        self.assertFalse(world_row['exists'])
        self.assertTrue(world_row['virtual'])
        self.assertTrue(body['integrity']['needs_repair'])

    def test_git_working_tree_does_not_mutate_head_when_layout_is_incomplete(self):
        book_id, repo_dir = self._init_book(book_name='v56_git_read_guard')
        broken_head = self._reset_to_metadata_only_commit(repo_dir)

        resp = self.client.get('/books/git_working_tree', query_string={'book_id': book_id})
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body['code'], 'LAYOUT_REPAIR_REQUIRED')

        after_head = self._git(repo_dir, 'rev-parse', 'HEAD')
        self.assertEqual(after_head, broken_head)

    def test_repair_layout_restores_integrity_after_reset(self):
        book_id, repo_dir = self._init_book(book_name='v56_repair_layout')
        broken_head = self._reset_to_metadata_only_commit(repo_dir)

        resp = self.client.post('/books/repair_layout', json={'book_id': book_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body['integrity']['needs_repair'])
        self.assertTrue((repo_dir / 'world_model.md').exists())
        self.assertTrue((repo_dir / 'status_card.md').exists())
        self.assertNotEqual(body['head_commit'], broken_head)

    def test_deduce_stream_blocks_when_layout_is_incomplete(self):
        book_id, repo_dir = self._init_book(book_name='v56_deduce_block')
        self._reset_to_metadata_only_commit(repo_dir)

        resp = self.client.post(
            '/api/world/deduce_stream',
            json={
                'book_id': book_id,
                'intent': '测试阻断',
                'active_file': 'world_model.md',
            },
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body['code'], 'LAYOUT_REPAIR_REQUIRED')


if __name__ == '__main__':
    unittest.main()
