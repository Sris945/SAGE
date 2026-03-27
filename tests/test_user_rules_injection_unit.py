import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock


class TestUserRulesInjection(unittest.TestCase):
    def test_universal_prefix_includes_user_rules_block(self):
        from sage.orchestrator.prefix_builder import build_prefix_for_agent

        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            sage_dir = repo_dir / ".sage"
            sage_dir.mkdir(parents=True, exist_ok=True)

            # Global rules injection comes from ~/.sage; for this unit test we
            # focus on project + agent-specific blocks.
            (sage_dir / "rules.md").write_text("## Project Rules\n- project\n")
            (sage_dir / "rules.coder.md").write_text("## Coder Rules\n- coder-specific\n")

            state = {
                "session_memory": {"codebase_brief": {"mode": "existing_repo"}},
                "retrieved_fix_patterns": [],
                "repo_path": str(repo_dir),
                "user_prompt": "build something",
                "last_error": "",
                "insight_feed": MagicMock(get_injected_context=MagicMock(return_value="")),
            }

            prefix = build_prefix_for_agent(state, agent_role="coder", task_id="t1")
            self.assertIn("USER RULES:", prefix)
            self.assertIn("project", prefix)
            self.assertIn("coder-specific", prefix)


if __name__ == "__main__":
    unittest.main()
