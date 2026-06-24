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

    1. the name must be a safe bare stem (:func:`is_valid_name` — no path
       separators, no ``.`` / ``..``); and
    2. defence-in-depth, the resolved file must stay inside the resolved
       portfolio directory.

    Either check failing raises :class:`ValueError` before any filesystem access.

    Raises:
        ValueError: If ``name`` is unsafe or resolves outside ``directory``.
    """
    if not is_valid_name(name):
        msg = (
            f"Invalid portfolio name {name!r}: only letters, digits, '_' and '-' "
            "are allowed (it is used as a filename)."
        )
        raise ValueError(msg)
    root = _resolve_dir(directory)
    path = root / f"{name}.yaml"
    if not path.resolve().is_relative_to(root.resolve()):
        msg = f"Portfolio name {name!r} resolves outside the portfolio directory {root}."
        raise ValueError(msg)
    return path


def load_portfolio(name: str, directory: Path | None = None) -> Portfolio:
    """Read and parse a portfolio file by name."""
    path = portfolio_path(name, directory)
    # CodeQL py/path-injection is suppressed on the next two lines: portfolio_path()
    # rejects any name that isn't a safe stem AND enforces directory containment
    # before returning (see its docstring), so ``path`` cannot traverse out of the
    # portfolio directory. CodeQL does not track that interprocedural barrier.
    if not path.exists():  # codeql[py/path-injection]
        raise FileNotFoundError(f"Portfolio {name!r} not found at {path}")
    text = path.read_text(encoding="utf-8")  # codeql[py/path-injection]
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
    # CodeQL py/path-injection suppressed: portfolio_path() validated the name and
    # enforced directory containment (see its docstring), so ``path`` is confined to
    # the portfolio directory. CodeQL does not track that interprocedural barrier.
    if not path.exists():  # codeql[py/path-injection]
        return False
    path.unlink()  # codeql[py/path-injection]
    logger.info("portfolio_deleted", name=name, path=str(path))
    return True
