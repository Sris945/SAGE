import os
import unittest
from pathlib import Path
from unittest import mock

from sage.config.paths import bundled_models_yaml, resolved_models_yaml_path


class TestConfigPaths(unittest.TestCase):
    def test_bundled_models_exists(self) -> None:
        p = bundled_models_yaml()
        self.assertTrue(p.is_file(), msg=f"missing {p}")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_resolved_defaults_to_bundled_without_user_file(self) -> None:
        with mock.patch("sage.config.paths.user_config_dir") as ucd:
            fake = Path("/nonexistent/no_sage_config")
            ucd.return_value = fake
            p = resolved_models_yaml_path()
            self.assertEqual(p, bundled_models_yaml())


if __name__ == "__main__":
    unittest.main()
