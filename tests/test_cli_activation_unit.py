"""Bare `sage` routes to help when non-interactive."""

import io
import os
from unittest.mock import MagicMock, patch


def test_bare_sage_prints_help_when_not_tty():
    import sage.cli.main as cli

    stdin = MagicMock()
    stdin.isatty.return_value = False

    with patch("sage.cli.branding.sys.stdin", stdin):
        with patch("sys.argv", ["sage"]):
            with patch("sys.stdout", new=io.StringIO()) as out:
                cli.main()
                text = out.getvalue().lower()
                assert "usage" in text or "quickstart" in text


def test_bare_sage_respects_sage_non_interactive():
    import sage.cli.main as cli

    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch("sage.cli.branding.sys.stdin", stdin):
        with patch.dict(os.environ, {"SAGE_NON_INTERACTIVE": "1"}):
            with patch("sys.argv", ["sage"]):
                with patch("sys.stdout", new=io.StringIO()) as out:
                    cli.main()
                    text = out.getvalue().lower()
                    assert "usage" in text or "quickstart" in text
