"""Tests for portfolio filesystem storage helpers.

We exercise the happy path (save → list → load), the error path
(loading something that doesn't exist, deleting something that doesn't
exist, saving an invalid portfolio), and the safety net for
file-vs-name mismatch.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cryptrink.portfolio.models import Allocation, Portfolio
from cryptrink.portfolio.storage import (
    delete_portfolio,
    list_portfolio_names,
    load_portfolio,
    portfolio_path,
    save_portfolio,
)


def _make_portfolio(name: str = "test") -> Portfolio:
    return Portfolio(
        name=name,
        timeframe="1h",
        initial_balance=Decimal("10000"),
        allocations=[
            Allocation(symbol="BTC-EUR", strategy_name="rsi_mean_reversion"),
        ],
    )


class TestRoundTrip:
    def test_save_then_load(self, tmp_path: Path) -> None:
        portfolio = _make_portfolio("alpha")
        path = save_portfolio(portfolio, directory=tmp_path)
        assert path.exists()
        assert path == tmp_path / "alpha.yaml"

        loaded = load_portfolio("alpha", directory=tmp_path)
        assert loaded == portfolio

    def test_list_names_sorted(self, tmp_path: Path) -> None:
        save_portfolio(_make_portfolio("zulu"), directory=tmp_path)
        save_portfolio(_make_portfolio("alpha"), directory=tmp_path)
        save_portfolio(_make_portfolio("mike"), directory=tmp_path)
        assert list_portfolio_names(directory=tmp_path) == ["alpha", "mike", "zulu"]

    def test_save_creates_missing_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "sub" / "portfolios"
        save_portfolio(_make_portfolio(), directory=nested)
        assert nested.is_dir()


class TestErrors:
    def test_load_missing_raises_filenotfound(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_portfolio("nope", directory=tmp_path)

    def test_save_rejects_invalid_portfolio(self, tmp_path: Path) -> None:
        # Empty allocations list is invalid; save_portfolio should
        # refuse rather than write a half-baked file to disk.
        bad = Portfolio(
            name="empty",
            timeframe="1h",
            initial_balance=Decimal("10000"),
            allocations=[],
        )
        with pytest.raises(ValueError, match="Cannot save invalid portfolio"):
            save_portfolio(bad, directory=tmp_path)
        assert not (tmp_path / "empty.yaml").exists()

    def test_load_detects_filename_name_mismatch(self, tmp_path: Path) -> None:
        # Manually plant a file whose internal name disagrees with
        # the filename — that's the operator-renamed-by-mistake case.
        portfolio_path("alpha", directory=tmp_path).parent.mkdir(parents=True, exist_ok=True)
        portfolio = _make_portfolio("not_alpha")
        save_portfolio(portfolio, directory=tmp_path)
        # Rename the file but keep the YAML's own ``name`` field.
        (tmp_path / "not_alpha.yaml").rename(tmp_path / "renamed.yaml")
        with pytest.raises(ValueError, match="does not match"):
            load_portfolio("renamed", directory=tmp_path)


class TestDelete:
    def test_delete_returns_true_on_success(self, tmp_path: Path) -> None:
        save_portfolio(_make_portfolio("alpha"), directory=tmp_path)
        assert delete_portfolio("alpha", directory=tmp_path) is True
        assert not (tmp_path / "alpha.yaml").exists()

    def test_delete_returns_false_when_missing(self, tmp_path: Path) -> None:
        assert delete_portfolio("nope", directory=tmp_path) is False


class TestEmptyDirectory:
    def test_list_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert list_portfolio_names(directory=tmp_path / "does_not_exist") == []


class TestPathTraversal:
    """A tampered name must never read/write/delete outside the portfolio dir."""

    @pytest.mark.parametrize(
        "evil",
        [
            "../evil",
            "../../etc/passwd",
            "/etc/passwd",
            "sub/evil",
            "..",
            "a.b",  # a dot is not allowed in a bare stem
            "with space",
        ],
    )
    def test_portfolio_path_rejects_unsafe_names(self, evil: str, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"Invalid portfolio name|resolves outside"):
            portfolio_path(evil, directory=tmp_path)

    def test_load_rejects_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid portfolio name"):
            load_portfolio("../../etc/passwd", directory=tmp_path)

    def test_delete_rejects_traversal(self, tmp_path: Path) -> None:
        # Must raise (reject), not silently no-op, and must not touch the file.
        with pytest.raises(ValueError, match="Invalid portfolio name"):
            delete_portfolio("../../etc/passwd", directory=tmp_path)
