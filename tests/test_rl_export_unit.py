import json
import tempfile
import unittest
from pathlib import Path

from sage.rl.export_dataset import export_routing_rows
from sage.rl.reward import composite_reward
from sage.rl.schema import ROUTING_SCHEMA_VERSION


class TestRLExport(unittest.TestCase):
    def test_composite_reward_v1(self):
        r = composite_reward(
            trajectory_reward=0.8,
            verification_passed=True,
            terminal=True,
            reward_version="reward_v1",
        )
        self.assertGreater(r, 0.8)

    def test_export_rows_from_trajectory(self):
        ev = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "task_id": "t1",
            "agent": "reviewer",
            "action": {"model_chosen": "m-primary", "prompt_strategy_key": ""},
            "reward": 0.9,
            "terminal": True,
            "state": {
                "verification_passed": True,
                "task_complexity_score": 0.3,
                "primary_failure_count": 0,
            },
            "extra": {"synthetic": True},
        }
        from unittest.mock import MagicMock

        router = MagicMock()
        router.get_primary_fallback.return_value = ("m-primary", "m-fallback")

        rows = export_routing_rows([("2025-01-01", ev)], router=router)
        self.assertTrue(len(rows) >= 1)
        self.assertEqual(rows[0].schema_version, ROUTING_SCHEMA_VERSION)
        self.assertEqual(rows[0].action_fallback, 0)
        self.assertEqual(rows[0].data_source, "synthetic")

    def test_export_logs_to_jsonl_meta(self):
        from sage.rl.export_dataset import export_logs_to_jsonl

        line = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "session_id": "sessA",
            "task_id": "t1",
            "agent": "reviewer",
            "action": {"model_chosen": "qwen2.5-coder:1.5b", "prompt_strategy_key": ""},
            "reward": 0.5,
            "terminal": True,
            "state": {"task_complexity_score": 0.1, "primary_failure_count": 0},
        }
        with tempfile.TemporaryDirectory() as d:
            log_dir = Path(d) / "sessions"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "2025-01-01.log"
            log_file.write_text(json.dumps(line) + "\n", encoding="utf-8")
            out = Path(d) / "out.jsonl"
            meta = export_logs_to_jsonl(log_dir=log_dir, output_path=out)
            self.assertTrue(out.exists())
            self.assertIn("row_count", meta)
            self.assertTrue(meta.get("below_recommended", True))

    def test_export_session_filter(self):
        from sage.rl.export_dataset import export_logs_to_jsonl

        line_a = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "session_id": "sessA",
            "task_id": "t1",
            "agent": "reviewer",
            "action": {"model_chosen": "qwen2.5-coder:1.5b", "prompt_strategy_key": ""},
            "reward": 0.5,
            "terminal": True,
            "state": {"task_complexity_score": 0.1, "primary_failure_count": 0},
        }
        line_b = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:01+00:00",
            "session_id": "sessB",
            "task_id": "t2",
            "agent": "reviewer",
            "action": {
                "model_chosen": "qwen2.5-coder:14b-instruct-q4_K_M",
                "prompt_strategy_key": "",
            },
            "reward": 0.1,
            "terminal": True,
            "state": {"task_complexity_score": 0.2, "primary_failure_count": 1},
        }
        with tempfile.TemporaryDirectory() as d:
            log_dir = Path(d) / "sessions"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "2025-01-01.log"
            log_file.write_text(
                json.dumps(line_a) + "\n" + json.dumps(line_b) + "\n", encoding="utf-8"
            )
            out = Path(d) / "out.jsonl"
            meta = export_logs_to_jsonl(
                log_dir=log_dir,
                output_path=out,
                session_id="sessA",
            )
            self.assertEqual(meta.get("row_count"), 1)

    def test_export_data_source_filter(self):
        from sage.rl.export_dataset import export_logs_to_jsonl, load_routing_jsonl

        real_line = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "session_id": "sessA",
            "task_id": "t1",
            "agent": "reviewer",
            "action": {"model_chosen": "qwen2.5-coder:1.5b", "prompt_strategy_key": ""},
            "reward": 0.5,
            "terminal": True,
            "state": {"task_complexity_score": 0.1, "primary_failure_count": 0},
        }
        synth_line = {
            "type": "TRAJECTORY_STEP",
            "timestamp": "2025-01-01T00:00:01+00:00",
            "session_id": "sessB",
            "task_id": "t2",
            "agent": "reviewer",
            "action": {
                "model_chosen": "qwen2.5-coder:14b-instruct-q4_K_M",
                "prompt_strategy_key": "",
            },
            "reward": 0.1,
            "terminal": True,
            "state": {"task_complexity_score": 0.2, "primary_failure_count": 1},
            "extra": {"synthetic": True},
        }
        with tempfile.TemporaryDirectory() as d:
            log_dir = Path(d) / "sessions"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "2025-01-01.log"
            log_file.write_text(
                json.dumps(real_line) + "\n" + json.dumps(synth_line) + "\n", encoding="utf-8"
            )

            out_real = Path(d) / "out_real.jsonl"
            meta_real = export_logs_to_jsonl(
                log_dir=log_dir,
                output_path=out_real,
                data_source="real",
            )
            rows_real = load_routing_jsonl(out_real)
            self.assertEqual(meta_real.get("row_count"), 1)
            self.assertEqual(meta_real.get("data_source_filter"), "real")
            self.assertEqual(rows_real[0].get("data_source"), "real")

            out_synth = Path(d) / "out_synth.jsonl"
            meta_synth = export_logs_to_jsonl(
                log_dir=log_dir,
                output_path=out_synth,
                data_source="synthetic",
            )
            rows_synth = load_routing_jsonl(out_synth)
            self.assertEqual(meta_synth.get("row_count"), 1)
            self.assertEqual(meta_synth.get("data_source_filter"), "synthetic")
            self.assertEqual(rows_synth[0].get("data_source"), "synthetic")


if __name__ == "__main__":
    unittest.main()
