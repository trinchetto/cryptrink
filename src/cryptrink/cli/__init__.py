"""CLI package for Cryptrink.

The Typer ``app`` is defined in :mod:`cryptrink.cli.main` and re-exported here
so the project script entrypoint (``cryptrink = "cryptrink.cli:app"``) keeps
working after the package was split out of the legacy single-file ``cli.py``.
"""

from cryptrink.cli import formatters, utils
from cryptrink.cli.main import app

__all__ = ["app", "formatters", "utils"]
