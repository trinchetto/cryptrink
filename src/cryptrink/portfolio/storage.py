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
from cryptrink.portfolio.models import Portfolio, dump_yaml, is_valid_name, load_yaml

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
    """Return the on-disk path for a portfolio by name.

    ``name`` is attacker-influenceable (it flows from the UI dropdown / YAML
    ``name`` field, which a tampered request could set to anything), so this is
    the single choke point that guards every read/write/delete against path
    traversal:

    1. the name must already be a bare basename (``Path(name).name == name``)
       and a safe stem (:func:`is_valid_name` — no path separators, no ``.`` /
       ``..``); and
    2. the path is resolved and confirmed to stay inside the resolved portfolio
       directory before it is returned.

    Either check failing raises :class:`ValueError` before any filesystem access.
    Returns the **resolved absolute** path — building every read/write/delete from
    this guarded value is what neutralises the path-traversal risk.

    Raises:
        ValueError: If ``name`` is unsafe or resolves outside ``directory``.
    """
    safe_name = Path(name).name
    if safe_name != name or not is_valid_name(safe_name):
        msg = (
            f"Invalid portfolio name {name!r}: only letters, digits, '_' and '-' "
            "are allowed (it is used as a filename)."
        )
        raise ValueError(msg)

    root_resolved = _resolve_dir(directory).resolve()
    path = (root_resolved / f"{safe_name}.yaml").resolve()
    if not path.is_relative_to(root_resolved):
        msg = f"Portfolio name {name!r} resolves outside the portfolio directory {root_resolved}."
        raise ValueError(msg)
    return path


def load_portfolio(name: str, directory: Path | None = None) -> Portfolio:
    """Read and parse a portfolio file by name."""
    # portfolio_path() returns a resolved path proven to sit inside the portfolio
    # directory (name validated + containment-checked), so it is safe to read.
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
    # portfolio_path() returns a resolved path proven to sit inside the portfolio
    # directory (name validated + containment-checked), so it is safe to delete.
    path = portfolio_path(name, directory)
    if not path.exists():
        return False
    path.unlink()
    logger.info("portfolio_deleted", name=name, path=str(path))
    return True
