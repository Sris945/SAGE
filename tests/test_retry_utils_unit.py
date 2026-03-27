import unittest


class TestRetryUtils(unittest.TestCase):
    def test_retry_call_eventual_success(self):
        from sage.utils.retry import retry_call

        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("temporary")
            return "ok"

        out = retry_call(flaky, retries=3, initial_delay_s=0.0, backoff=1.0)
        self.assertEqual(out, "ok")
        self.assertEqual(state["n"], 3)

    def test_retry_call_raises_last_error(self):
        from sage.utils.retry import retry_call

        state = {"n": 0}

        def broken():
            state["n"] += 1
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            retry_call(broken, retries=2, initial_delay_s=0.0, backoff=1.0)
        self.assertEqual(state["n"], 3)


if __name__ == "__main__":
    unittest.main()
