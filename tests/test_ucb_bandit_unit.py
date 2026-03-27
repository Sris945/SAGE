import unittest


class TestUCBBandit(unittest.TestCase):
    def test_update_and_select_prefers_higher_reward(self):
        from sage.rl.ucb_bandit import UCBStrategyBandit

        b = UCBStrategyBandit()
        # Ensure exploration picks the first untried key deterministically.
        first = b.select(strategy_keys=["coder:primary", "coder:fallback"])
        self.assertEqual(first, "coder:primary")

        # Update both strategies once with different rewards.
        b.update(strategy_key="coder:primary", reward=1.0)
        b.update(strategy_key="coder:fallback", reward=0.0)

        # Now selection should prefer primary (higher mean).
        picked = b.select(strategy_keys=["coder:primary", "coder:fallback"])
        self.assertEqual(picked, "coder:primary")


if __name__ == "__main__":
    unittest.main()
