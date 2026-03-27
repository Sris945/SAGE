import tempfile
import unittest
from pathlib import Path


class TestGitHooks(unittest.TestCase):
    def test_post_commit_hook_is_installed_when_git_dir_exists(self):
        from sage.scripts.git_hooks import ensure_post_commit_hook

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

            ensure_post_commit_hook(repo_dir=repo)

            hook_path = repo / ".git" / "hooks" / "post-commit"
            self.assertTrue(hook_path.exists())
            # chmod should mark it executable for best-effort
            mode = hook_path.stat().st_mode
            self.assertTrue(mode & 0o111)


if __name__ == "__main__":
    unittest.main()
