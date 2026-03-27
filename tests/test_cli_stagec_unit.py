import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestCliStageC(unittest.TestCase):
    def test_config_validate_success(self):
        import sage.cli.main as cli

        with patch("sys.argv", ["sage", "config", "validate"]):
            with patch("sys.stdout", new=io.StringIO()) as out:
                cli.main()
                self.assertIn("valid", out.getvalue())

    def test_doctor_json(self):
        import sage.cli.main as cli

        def fake_run(cmd, capture_output=True, text=True, timeout=5):  # noqa: ARG001
            class R:
                returncode = 0
                if cmd and cmd[0] == "ollama":
                    stdout = "NAME ID SIZE MODIFIED\nqwen2.5-coder:1.5b x 1GB now\n"
                else:
                    stdout = "ok"
                stderr = ""

            return R()

        with patch("subprocess.run", side_effect=fake_run):
            with patch("sys.argv", ["sage", "doctor", "--json"]):
                with patch("sys.stdout", new=io.StringIO()) as out:
                    cli.main()
                    payload = json.loads(out.getvalue())
                    self.assertIn("python", payload)
                    self.assertIn("models_yaml", payload)
                    self.assertIn("ollama", payload)
                    self.assertIn("configured_models_present", payload)
                    self.assertIn("health_summary", payload)
                    self.assertEqual(payload["health_summary"]["status"], "degraded")
                    detail = payload["configured_models_present"]["detail"]
                    self.assertIn("external_configured", detail)
                    self.assertIn("claude-sonnet-4-5", detail["external_configured"])

    def test_config_set_updates_role(self):
        import sage.cli.main as cli

        cfg = {
            "routing": {
                "coder": {
                    "primary": "a",
                    "fallback": "b",
                    "fallback_triggers": ["primary_failure_count >= 2"],
                }
            }
        }

        def fake_load():
            return cfg

        saved = {}

        def fake_save(data, path=None):  # noqa: ARG001
            saved["data"] = data

        with patch("sage.cli.main._load_models_config", side_effect=fake_load):
            with patch("sage.cli.main._save_models_config", side_effect=fake_save):
                with patch(
                    "sys.argv",
                    [
                        "sage",
                        "config",
                        "set",
                        "--role",
                        "coder",
                        "--primary",
                        "new-primary",
                        "--fallback",
                        "new-fallback",
                    ],
                ):
                    with patch("sys.stdout", new=io.StringIO()):
                        cli.main()

        self.assertIn("data", saved)
        role_cfg = saved["data"]["routing"]["coder"]
        self.assertEqual(role_cfg["primary"], "new-primary")
        self.assertEqual(role_cfg["fallback"], "new-fallback")

    def test_explain_routing_summary_helper(self):
        from sage.cli import log_utils

        sample = [
            {
                "type": "MODEL_ROUTING_DECISION",
                "session_id": "sess1",
                "agent_role": "coder",
                "policy_source": "yaml",
            },
            {
                "type": "MODEL_ROUTING_DECISION",
                "session_id": "sess1",
                "agent_role": "reviewer",
                "policy_source": "learned",
            },
            {
                "type": "MODEL_ROUTING_DECISION",
                "session_id": "other",
                "agent_role": "coder",
                "policy_source": "yaml",
            },
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in sample), encoding="utf-8")
            with patch("sage.cli.log_utils.today_session_log_path", return_value=p):
                with patch("sys.stdout", new=io.StringIO()) as out:
                    log_utils.print_routing_summary_for_session("sess1")
                    txt = out.getvalue()
                    self.assertIn("routing decisions", txt)
                    self.assertIn("coder", txt)
                    self.assertIn("reviewer", txt)

    def test_cli_help_smoke(self):
        import sage.cli.main as cli

        with patch("sys.argv", ["sage", "--help"]):
            with patch("sys.stdout", new=io.StringIO()) as out:
                # argparse exits with SystemExit(0)
                try:
                    cli.main()
                except SystemExit:
                    pass
                self.assertIn("Quickstart", out.getvalue())
                self.assertIn("sage doctor", out.getvalue())

    def test_shell_parse_error(self):
        import sage.cli.main as cli

        with patch("rich.prompt.Prompt.ask", side_effect=['/run "unterminated', "/exit"]):
            with patch("sys.stdout", new=io.StringIO()) as out:
                cli.cmd_shell(None)
                self.assertIn("parse error", out.getvalue())


if __name__ == "__main__":
    unittest.main()
