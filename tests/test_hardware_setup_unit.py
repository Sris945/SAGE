import unittest

from sage.cli.hardware_setup import (
    HardwareProfile,
    suggest_ollama_stack,
)


class TestHardwareSetup(unittest.TestCase):
    def test_suggest_minimal_tier_low_vram(self):
        p = HardwareProfile(os_name="linux", ram_gib=8.0, vram_gib=4.0)
        s = suggest_ollama_stack(p, disk_budget_gib=20.0)
        self.assertEqual(s["tier"], "minimal")
        self.assertIn("qwen2.5-coder:1.5b", s["ollama_tags"])

    def test_suggest_balanced_high_vram(self):
        p = HardwareProfile(os_name="linux", ram_gib=32.0, vram_gib=16.0)
        s = suggest_ollama_stack(p, disk_budget_gib=22.0)
        self.assertIn(s["tier"], ("balanced", "comfortable"))
        self.assertTrue(any("14b" in t for t in s["ollama_tags"]))


if __name__ == "__main__":
    unittest.main()
