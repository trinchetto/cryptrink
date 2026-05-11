"""Tests for :func:`build_portfolio_from_balances`.

The import helper is pure of database / network concerns by design,
which lets us drive it with a small fake exchange and pin every part
of its contract:

* the quote currency is the **fiat with the largest balance**,
* crypto whose pair doesn't exist on the exchange is **skipped** (not
  silently dropped) and surfaced via :attr:`ImportResult.skipped`,
* weights sum to ``< 1`` (cash takes the remainder) and reflect each
  allocation's share of total equity,
* the helper refuses to build a portfolio with no fiat or no crypto.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest

from cryptrink.exchange.base import Balance, Ticker
from cryptrink.portfolio.import_ import KNOWN_FIATS, build_portfolio_from_balances

if TYPE_CHECKING:
    from datetime import datetime

    from cryptrink.exchange.base import BaseExchange


class _FakeExchange:
    """Minimal stand-in for :class:`BaseExchange` exposing balances + tickers.

    The import helper only calls ``get_balances`` and ``get_ticker``;
    keeping this class small (rather than subclassing
    :class:`BaseExchange` and implementing 20 abstract methods) is the
    cheapest way to exercise the helper in isolation.
    """

    def __init__(
        self,
        balances: dict[str, Decimal],
        tickers: dict[str, Decimal],
    ) -> None:
        self._balances = {
            ccy: Balance(currency=ccy, available=qty, locked=Decimal("0"))
            for ccy, qty in balances.items()
        }
        self._tickers = tickers

    async def get_balances(self) -> dict[str, Balance]:
        return dict(self._balances)

    async def get_ticker(self, symbol: str) -> Ticker:
        if symbol not in self._tickers:
            raise ValueError(f"No ticker for {symbol}")
        from datetime import UTC, datetime

        last = self._tickers[symbol]
        return Ticker(
            symbol=symbol,
            bid=last,
            ask=last,
            last=last,
            volume_24h=Decimal("0"),
            high_24h=last,
            low_24h=last,
            timestamp=cast("datetime", datetime.now(UTC)),
        )


def _exchange(
    balances: dict[str, Decimal],
    tickers: dict[str, Decimal],
) -> BaseExchange:
    """Cast a :class:`_FakeExchange` to the expected type for static checkers."""
    return cast("BaseExchange", _FakeExchange(balances, tickers))


class TestQuoteCurrencySelection:
    @pytest.mark.asyncio
    async def test_picks_fiat_with_largest_balance(self) -> None:
        exchange = _exchange(
            balances={
                "EUR": Decimal("100"),
                "USD": Decimal("5000"),
                "BTC": Decimal("0.1"),
            },
            tickers={"BTC-USD": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange)
        assert result.quote_currency == "USD"
        assert result.portfolio.allocations[0].symbol == "BTC-USD"

    @pytest.mark.asyncio
    async def test_ignores_zero_fiat_balances(self) -> None:
        exchange = _exchange(
            balances={
                "EUR": Decimal("0"),
                "USD": Decimal("100"),
                "BTC": Decimal("0.1"),
            },
            tickers={"BTC-USD": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange)
        assert result.quote_currency == "USD"

    @pytest.mark.asyncio
    async def test_known_fiats_set_used_for_partitioning(self) -> None:
        # Sanity check: the helper distinguishes fiat from crypto via
        # :data:`KNOWN_FIATS`. If somebody adds a new fiat (e.g. JPY)
        # they need to extend that set.
        assert "EUR" in KNOWN_FIATS
        assert "BTC" not in KNOWN_FIATS


class TestAllocationConstruction:
    @pytest.mark.asyncio
    async def test_weight_proportional_to_quote_value(self) -> None:
        exchange = _exchange(
            balances={
                "EUR": Decimal("5000"),
                "BTC": Decimal("0.1"),  # 0.1 * 50_000 = 5_000 EUR
                "ETH": Decimal("1"),  # 1 * 3_000 = 3_000 EUR
            },
            tickers={
                "BTC-EUR": Decimal("50000"),
                "ETH-EUR": Decimal("3000"),
            },
        )
        result = await build_portfolio_from_balances(exchange)
        # total_equity = 5_000 (cash) + 5_000 (BTC) + 3_000 (ETH) = 13_000
        assert result.total_equity == Decimal("13000")

        weights = {a.symbol: a.weight for a in result.portfolio.allocations}
        # BTC: 5_000 / 13_000 ≈ 0.384615
        # ETH: 3_000 / 13_000 ≈ 0.230769
        assert weights["BTC-EUR"] == pytest.approx(5000 / 13000, abs=1e-5)
        assert weights["ETH-EUR"] == pytest.approx(3000 / 13000, abs=1e-5)
        # Cash share is implicit (1 - sum(allocation weights)).
        assert sum(weights.values()) == pytest.approx(8000 / 13000, abs=1e-5)

    @pytest.mark.asyncio
    async def test_allocations_sorted_by_descending_value(self) -> None:
        # ETH > BTC > LTC by quote value: the YAML lists them in the
        # same order so the most material position is at the top.
        exchange = _exchange(
            balances={
                "EUR": Decimal("100"),
                "BTC": Decimal("0.01"),  # 500 EUR
                "ETH": Decimal("2"),  # 6_000 EUR
                "LTC": Decimal("5"),  # 250 EUR
            },
            tickers={
                "BTC-EUR": Decimal("50000"),
                "ETH-EUR": Decimal("3000"),
                "LTC-EUR": Decimal("50"),
            },
        )
        result = await build_portfolio_from_balances(exchange)
        symbols = [a.symbol for a in result.portfolio.allocations]
        assert symbols == ["ETH-EUR", "BTC-EUR", "LTC-EUR"]

    @pytest.mark.asyncio
    async def test_strategy_name_propagated(self) -> None:
        exchange = _exchange(
            balances={"EUR": Decimal("100"), "BTC": Decimal("0.1")},
            tickers={"BTC-EUR": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange, strategy_name="sma_crossover")
        assert all(a.strategy_name == "sma_crossover" for a in result.portfolio.allocations)

    @pytest.mark.asyncio
    async def test_default_strategy_is_rsi(self) -> None:
        exchange = _exchange(
            balances={"EUR": Decimal("100"), "BTC": Decimal("0.1")},
            tickers={"BTC-EUR": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange)
        assert result.portfolio.allocations[0].strategy_name == "rsi_mean_reversion"

    @pytest.mark.asyncio
    async def test_timeframe_propagated(self) -> None:
        exchange = _exchange(
            balances={"EUR": Decimal("100"), "BTC": Decimal("0.1")},
            tickers={"BTC-EUR": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange, timeframe="4h")
        assert result.portfolio.timeframe == "4h"


class TestSkippedHoldings:
    @pytest.mark.asyncio
    async def test_unpriceable_crypto_is_skipped_not_dropped(self) -> None:
        # USDT has a balance but no USDT-EUR pair: the helper should
        # record it on ``skipped`` with a human-readable warning.
        exchange = _exchange(
            balances={
                "EUR": Decimal("100"),
                "BTC": Decimal("0.1"),
                "USDT": Decimal("500"),
            },
            tickers={"BTC-EUR": Decimal("50000")},
        )
        result = await build_portfolio_from_balances(exchange)
        assert result.skipped == ["USDT"]
        assert any("USDT" in w for w in result.warnings)
        assert {a.symbol for a in result.portfolio.allocations} == {"BTC-EUR"}


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_no_fiat_balance_raises(self) -> None:
        exchange = _exchange(
            balances={"BTC": Decimal("0.1")},
            tickers={"BTC-EUR": Decimal("50000")},
        )
        with pytest.raises(ValueError, match="No fiat balance"):
            await build_portfolio_from_balances(exchange)

    @pytest.mark.asyncio
    async def test_no_crypto_holdings_raises(self) -> None:
        exchange = _exchange(
            balances={"EUR": Decimal("1000")},
            tickers={},
        )
        with pytest.raises(ValueError, match="nothing to allocate"):
            await build_portfolio_from_balances(exchange)

    @pytest.mark.asyncio
    async def test_every_crypto_failing_to_price_raises(self) -> None:
        # The dominant fiat is EUR, but no tradeable pair against it
        # exists for the operator's two crypto holdings. We refuse to
        # build a portfolio rather than silently returning an empty one.
        exchange = _exchange(
            balances={
                "EUR": Decimal("1000"),
                "BTC": Decimal("0.1"),
                "ETH": Decimal("1"),
            },
            tickers={},
        )
        with pytest.raises(ValueError, match="failed to price"):
            await build_portfolio_from_balances(exchange)
