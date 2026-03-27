import unittest

from sage.llm.token_budget import clamp_messages_chars


class TestTokenBudget(unittest.TestCase):
    def test_clamp_messages(self) -> None:
        msgs = [
            {"role": "system", "content": "x" * 500},
            {"role": "user", "content": "y" * 500},
        ]
        out = clamp_messages_chars(msgs, max_total=400)
        total = sum(len(str(m.get("content") or "")) for m in out)
        self.assertLessEqual(total, 400)


if __name__ == "__main__":
    unittest.main()
