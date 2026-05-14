"""Filesystem storage for portfolio YAML files.

Portfolios live as ``data/portfolios/<name>.yaml`` so they:

* are diff-able and review-able alongside the code,
* can be hand-edited without launching the UI,
* are easy to version, copy between environments, and back up.

The default root is ``<repo>/data/portfolios``; a custom root can be
passed in for tests.
"""

from __future__ import annotations

from pathlib import Path

from cryptrink.core.logging import get_logger
from cryptrink.portfolio.models import Portfolio, dump_yaml, load_yaml

logger = get_logger(__name__)


# Resolved at import time so the directory is consistent across processes.
# Falls back to ``./data/portfolios`` relative to the current working
# directory; the Gradio app boots from the repo root so this resolves to
# the same place as the on-disk SQLite DB.
DEFAULT_PORTFOLIO_DIR = Path("data/portfolios")


def _resolve_dir(directory: Path | None) -> Path:
    return directory if directory is not None else DEFAULT_PORTFOLIO_DIR


def list_portfolio_names(directory: Path | None = None) -> list[str]:
    """Return the names of every saved portfolio, sorted.

    A "name" is the YAML file's stem (``btc_eth.yaml`` → ``btc_eth``).
    Missing directories return an empty list — the UI uses this to
    decide whether to show the empty-state hint.
    """
    root = _resolve_dir(directory)
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.yaml") if p.is_file())


def portfolio_path(name: str, directory: Path | None = None) -> Path:
    """Return the on-disk path for a portfolio by name."""
    return _resolve_dir(directory) / f"{name}.yaml"


def load_portfolio(name: str, directory: Path | None = None) -> Portfolio:
    """Read and parse a portfolio file by name."""
    path = portfolio_path(name, directory)
    if not path.exists():
        raise FileNotFoundError(f"Portfolio {name!r} not found at {path}")
    text = path.read_text(encoding="utf-8")
    portfolio = load_yaml(text)
    if portfolio.name != name:
        # Be loud about a name/file mismatch — silently renaming the
        # in-memory portfolio to match the filename would let the
        # operator save back to a different file than they loaded
        # from. Better to fail and let them fix one or the other.
        raise ValueError(
            f"Portfolio name in file ({portfolio.name!r}) does not match "
            f"filename ({name!r}). Rename the file or update the YAML."
        )
    return portfolio


def save_portfolio(portfolio: Portfolio, directory: Path | None = None) -> Path:
    """Serialise and write a portfolio to ``<dir>/<name>.yaml``.

    Creates the directory if it doesn't exist. Returns the absolute path
    written so callers (the UI) can echo it back to the operator.
    """
    errors = portfolio.validate()
    if errors:
        raise ValueError("Cannot save invalid portfolio: " + "; ".join(errors))
    root = _resolve_dir(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = portfolio_path(portfolio.name, directory)
    path.write_text(dump_yaml(portfolio), encoding="utf-8")
    logger.info("portfolio_saved", name=portfolio.name, path=str(path))
    return path


def delete_portfolio(name: str, directory: Path | None = None) -> bool:
    """Delete a portfolio by name. Returns True if a file was removed."""
    path = portfolio_path(name, directory)
    if not path.exists():
        return False
    path.unlink()
    logger.info("portfolio_deleted", name=name, path=str(path))
    return True
