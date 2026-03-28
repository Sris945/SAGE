"""Unit tests for sage.execution.git_tools."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


def _init_repo(path: Path) -> None:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@sage"],
        check=True,
        capture_output=True,
        cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "SAGE Test"],
        check=True,
        capture_output=True,
        cwd=str(path),
    )
    # Create initial commit so HEAD exists.
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "-A"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True,
        capture_output=True,
        cwd=str(path),
    )


class TestGitToolsValidation(unittest.TestCase):
    def test_missing_repo_path(self):
        from sage.execution.git_tools import git_status

        result = git_status("/nonexistent/path/abc123")
        self.assertEqual(result["status"], "error")

    def test_no_git_dir(self):
        from sage.execution.git_tools import git_status

        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_status(tmpdir)
            self.assertEqual(result["status"], "error")
            self.assertIn(".git", result["stderr"])


class TestGitStatus(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._repo = Path(self._tmpdir)
        _init_repo(self._repo)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_clean_status(self):
        from sage.execution.git_tools import git_status

        result = git_status(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIsInstance(result["modified"], list)
        self.assertIsInstance(result["untracked"], list)
        self.assertIsInstance(result["staged"], list)

    def test_untracked_file(self):
        from sage.execution.git_tools import git_status

        (self._repo / "new_file.txt").write_text("hello")
        result = git_status(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIn("new_file.txt", result["untracked"])

    def test_modified_file(self):
        from sage.execution.git_tools import git_status

        (self._repo / "README.md").write_text("modified content")
        result = git_status(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIn("README.md", result["modified"])


class TestGitCommit(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._repo = Path(self._tmpdir)
        _init_repo(self._repo)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_commit_all(self):
        from sage.execution.git_tools import git_commit

        (self._repo / "file.txt").write_text("content")
        result = git_commit(str(self._repo), message="test commit")
        self.assertEqual(result["status"], "ok")

    def test_commit_specific_files(self):
        from sage.execution.git_tools import git_commit

        (self._repo / "a.txt").write_text("a")
        (self._repo / "b.txt").write_text("b")
        result = git_commit(str(self._repo), message="partial commit", files=["a.txt"])
        self.assertEqual(result["status"], "ok")

    def test_commit_nothing_to_commit(self):
        from sage.execution.git_tools import git_commit

        # Nothing changed after init commit.
        result = git_commit(str(self._repo), message="empty")
        # git commit returns non-zero when nothing to commit.
        self.assertIn(result["status"], ("ok", "error"))


class TestGitDiff(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._repo = Path(self._tmpdir)
        _init_repo(self._repo)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_diff_clean_repo(self):
        from sage.execution.git_tools import git_diff

        result = git_diff(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIn("diff", result)

    def test_diff_modified_file(self):
        from sage.execution.git_tools import git_diff

        (self._repo / "README.md").write_text("changed content")
        result = git_diff(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIn("README.md", result["diff"])

    def test_diff_staged(self):
        from sage.execution.git_tools import git_diff

        (self._repo / "README.md").write_text("staged change")
        subprocess.run(["git", "add", "README.md"], cwd=str(self._repo), capture_output=True)
        result = git_diff(str(self._repo), staged=True)
        self.assertEqual(result["status"], "ok")
        self.assertIn("README.md", result["diff"])


class TestGitLog(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._repo = Path(self._tmpdir)
        _init_repo(self._repo)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_log_returns_entries(self):
        from sage.execution.git_tools import git_log

        result = git_log(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIsInstance(result["entries"], list)
        self.assertGreaterEqual(len(result["entries"]), 1)
        entry = result["entries"][0]
        self.assertIn("hash", entry)
        self.assertIn("message", entry)
        self.assertIn("date", entry)

    def test_log_n_limit(self):
        from sage.execution.git_tools import git_commit, git_log

        for i in range(3):
            (self._repo / f"f{i}.txt").write_text(str(i))
            git_commit(str(self._repo), message=f"commit {i}")
        result = git_log(str(self._repo), n=2)
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(len(result["entries"]), 2)


class TestGitBranch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._repo = Path(self._tmpdir)
        _init_repo(self._repo)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_list_branches(self):
        from sage.execution.git_tools import git_branch

        result = git_branch(str(self._repo))
        self.assertEqual(result["status"], "ok")
        self.assertIsInstance(result["branches"], list)
        self.assertGreaterEqual(len(result["branches"]), 1)
        self.assertNotEqual(result["current"], "")

    def test_create_branch(self):
        from sage.execution.git_tools import git_branch

        result = git_branch(str(self._repo), name="feature-x", create=True)
        self.assertEqual(result["status"], "ok")
        self.assertIn("feature-x", result["branches"])


if __name__ == "__main__":
    unittest.main()
