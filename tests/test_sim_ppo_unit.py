import unittest

from sage.sim.ppo import train_ppo


class TestPPOStub(unittest.TestCase):
    def test_stub(self):
        r = train_ppo(steps=200, seed=1)
        self.assertEqual(r.get("status"), "ok")


if __name__ == "__main__":
    unittest.main()
