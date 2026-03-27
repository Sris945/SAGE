import unittest

from sage.prompt_engine import skill_injector as si


class TestSkillInjector(unittest.TestCase):
    def test_coder_injection_non_empty(self) -> None:
        si.clear_skill_text_cache()
        s = si.get_skill_injection_context(
            agent_role="coder",
            task_description="add pytest coverage",
            last_error="",
        )
        self.assertIn("sage:discipline:", s)
        self.assertGreater(len(s), 200)

    def test_planner_includes_plan_skills(self) -> None:
        si.clear_skill_text_cache()
        s = si.get_skill_injection_context(
            agent_role="planner",
            task_description="design api",
            last_error="",
        )
        self.assertIn("sage:planning:", s)

    def test_total_char_cap(self) -> None:
        import os

        si.clear_skill_text_cache()
        os.environ["SAGE_MAX_SKILL_CHARS_TOTAL"] = "400"
        try:
            s = si.get_skill_injection_context(
                agent_role="coder",
                task_description="",
                last_error="traceback",
            )
            self.assertLessEqual(len(s), 4500)
        finally:
            os.environ.pop("SAGE_MAX_SKILL_CHARS_TOTAL", None)


if __name__ == "__main__":
    unittest.main()
