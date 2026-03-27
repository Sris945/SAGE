import os
import unittest


class TestOllamaBenchTimeout(unittest.TestCase):
    def tearDown(self) -> None:
        for k in (
            "SAGE_BENCH",
            "SAGE_BENCH_TIMEOUT_MULT",
            "SAGE_BENCH_CHAT_MAX_S",
            "SAGE_BENCH_EMBED_MAX_S",
        ):
            os.environ.pop(k, None)

    def test_normal_mode_unchanged(self):
        from sage.llm.ollama_safe import effective_ollama_timeout

        self.assertEqual(effective_ollama_timeout(10.0, kind="chat"), 10.0)

    def test_bench_scales_chat(self):
        from sage.llm.ollama_safe import effective_ollama_timeout

        os.environ["SAGE_BENCH"] = "1"
        os.environ["SAGE_BENCH_TIMEOUT_MULT"] = "3"
        # 6 * 3 = 18
        self.assertEqual(effective_ollama_timeout(6.0, kind="chat"), 18.0)

    def test_bench_caps_chat(self):
        from sage.llm.ollama_safe import effective_ollama_timeout

        os.environ["SAGE_BENCH"] = "1"
        os.environ["SAGE_BENCH_TIMEOUT_MULT"] = "100"
        os.environ["SAGE_BENCH_CHAT_MAX_S"] = "60"
        self.assertEqual(effective_ollama_timeout(6.0, kind="chat"), 60.0)

    def test_bench_scales_embeddings(self):
        from sage.llm.ollama_safe import effective_ollama_timeout

        os.environ["SAGE_BENCH"] = "1"
        os.environ["SAGE_BENCH_TIMEOUT_MULT"] = "4"
        # 0.25 * 4 = 1.0
        self.assertEqual(effective_ollama_timeout(0.25, kind="embeddings"), 1.0)


if __name__ == "__main__":
    unittest.main()
