"""Tests for the ``/configuration/pairs`` lookup + ``PairInfo`` constraints."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from cryptrink.exchange.revolutx import PairInfo, RevolutXExchange


def _exchange() -> RevolutXExchange:
    return RevolutXExchange(
        api_key="api_key_for_test",
        # 32 zero bytes is a valid Ed25519 raw seed for signing in tests.
        private_key_base64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )


_BTC_USD_BODY = {
    "base": "BTC",
    "quote": "USD",
    "base_step": "0.0000001",
    "quote_step": "0.01",
    "min_order_size": "0.0001",
    "max_order_size": "1000",
    "min_order_size_quote": "1.00",
    "status": "active",
}


class TestGetPairInfos:
    @pytest.mark.asyncio
    async def test_normalises_symbol_keys_and_decimal_fields(self) -> None:
        exchange = _exchange()
        api_response = {
            "BTC/USD": _BTC_USD_BODY,
            "ETH/EUR": {
                **_BTC_USD_BODY,
                "base": "ETH",
                "quote": "EUR",
                "min_order_size": "0.001",
                "min_order_size_quote": "0.50",
            },
        }
        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value=api_response),
        ):
            infos = await exchange.get_pair_infos()

        assert set(infos.keys()) == {"BTC-USD", "ETH-EUR"}
        btc = infos["BTC-USD"]
        assert btc.base == "BTC"
        assert btc.quote == "USD"
        assert btc.min_order_size == Decimal("0.0001")
        assert btc.min_order_size_quote == Decimal("1.00")
        assert btc.max_order_size == Decimal("1000")
        assert btc.base_step == Decimal("0.0000001")
        assert btc.is_active() is True

    @pytest.mark.asyncio
    async def test_skips_malformed_entries_silently(self) -> None:
        """A single corrupt entry shouldn't break the whole lookup —
        the operator's pre-flight is more useful with one bad row missing
        than crashed."""
        exchange = _exchange()
        api_response = {
            "BTC/USD": _BTC_USD_BODY,
            "BAD/PAIR": "not even a dict",
            "ALSO/BAD": {"base_step": "not-a-number"},
        }
        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value=api_response),
        ):
            infos = await exchange.get_pair_infos()
        assert "BTC-USD" in infos
        assert "BAD-PAIR" not in infos
        assert "ALSO-BAD" not in infos

    @pytest.mark.asyncio
    async def test_handles_non_dict_response(self) -> None:
        exchange = _exchange()
        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value=[]),
        ):
            infos = await exchange.get_pair_infos()
        assert infos == {}


class TestPairInfoRejectReason:
    """``PairInfo.reject_reason`` is what the Live tab's pre-flight
    surfaces — the precise constraint that would trip is more useful than
    a generic 'order would be rejected'."""

    def _info(self, **overrides: object) -> PairInfo:
        defaults: dict[str, object] = {
            "symbol": "BTC-USD",
            "base": "BTC",
            "quote": "USD",
            "base_step": Decimal("0.0000001"),
            "quote_step": Decimal("0.01"),
            "min_order_size": Decimal("0.0001"),
            "max_order_size": Decimal("1000"),
            "min_order_size_quote": Decimal("1.00"),
            "status": "active",
        }
        defaults.update(overrides)
        return PairInfo(**defaults)  # type: ignore[arg-type]

    def test_active_clean_order_returns_none(self) -> None:
        info = self._info()
        # 0.001 BTC at $50 each = $50 notional — clears all minimums.
        assert info.reject_reason(quantity=Decimal("0.001"), notional=Decimal("50")) is None

    def test_inactive_pair_is_rejected(self) -> None:
        info = self._info(status="suspended")
        reason = info.reject_reason(quantity=Decimal("1"), notional=Decimal("1000"))
        assert reason is not None
        assert "suspended" in reason

    def test_quantity_below_min_order_size(self) -> None:
        """User scenario: €1 of BTC ≈ 0.0000167 BTC — below 0.0001 min."""
        info = self._info()
        reason = info.reject_reason(quantity=Decimal("0.0000167"), notional=Decimal("1"))
        assert reason is not None
        assert "min_order_size" in reason
        assert "BTC" in reason

    def test_quantity_above_max_order_size(self) -> None:
        info = self._info()
        reason = info.reject_reason(quantity=Decimal("9999"), notional=Decimal("9999"))
        assert reason is not None
        assert "max_order_size" in reason

    def test_notional_below_min_order_size_quote(self) -> None:
        """If base side passes but quote side fails (low-priced asset, tiny
        EUR), the quote check must still trip."""
        info = self._info(min_order_size=Decimal("0.000000001"))
        reason = info.reject_reason(quantity=Decimal("1"), notional=Decimal("0.50"))
        assert reason is not None
        assert "min_order_size_quote" in reason
