"""Tests for the /candles wrapper on RevolutXExchange."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from cryptrink.exchange.revolutx import (
    RevolutXExchange,
    timeframe_to_interval_minutes,
)


def _exchange() -> RevolutXExchange:
    """Build an exchange whose request layer is mock-friendly."""
    return RevolutXExchange(
        api_key="api_key_for_test",
        # 32 zero bytes is a valid Ed25519 raw seed for signing in tests.
        private_key_base64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )


class TestTimeframeMapping:
    @pytest.mark.parametrize(
        ("timeframe", "expected"),
        [
            ("1m", 1),
            ("5m", 5),
            ("15m", 15),
            ("30m", 30),
            ("1h", 60),
            ("4h", 240),
            ("1d", 1440),
            ("1w", 10080),
        ],
    )
    def test_known_timeframes(self, timeframe: str, expected: int) -> None:
        assert timeframe_to_interval_minutes(timeframe) == expected

    def test_unknown_timeframe_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported"):
            timeframe_to_interval_minutes("3m")


class TestGetCandles:
    @pytest.mark.asyncio
    async def test_passes_interval_and_returns_normalised_candles(self) -> None:
        exchange = _exchange()
        api_response = {
            "data": [
                {
                    "start": 1700000300000,
                    "open": "92087.81",
                    "high": "92133.89",
                    "low": "92052.39",
                    "close": "92067.31",
                    "volume": "0.00067964",
                },
                {
                    "start": 1700000000000,
                    "open": "90390.46",
                    "high": "90395",
                    "low": "90358.84",
                    "close": "90395",
                    "volume": "0.00230816",
                },
            ]
        }

        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value=api_response),
        ) as mock_request:
            candles = await exchange.get_candles(
                symbol="BTC-EUR",
                timeframe="5m",
                since_ms=1700000000000,
                until_ms=1700000300000,
            )

        # Endpoint, method, and the precise query params must match the spec.
        mock_request.assert_awaited_once()
        kwargs = mock_request.await_args.kwargs
        assert kwargs["params"]["interval"] == 5
        assert kwargs["params"]["since"] == 1700000000000
        assert kwargs["params"]["until"] == 1700000300000

        # Output is sorted ascending and shaped for OHLCVRepository.save_batch.
        assert [c["timestamp"] for c in candles] == [1700000000000, 1700000300000]
        first = candles[0]
        assert first["symbol"] == "BTC-EUR"
        assert first["timeframe"] == "5m"
        assert first["open"] == Decimal("90390.46")
        assert first["close"] == Decimal("90395")
        assert isinstance(first["volume"], Decimal)

    @pytest.mark.asyncio
    async def test_omits_optional_params_when_not_supplied(self) -> None:
        exchange = _exchange()
        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value={"data": []}),
        ) as mock_request:
            await exchange.get_candles(symbol="BTC-EUR", timeframe="1h")

        params = mock_request.await_args.kwargs["params"]
        assert params == {"interval": 60}
        assert "since" not in params
        assert "until" not in params

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self) -> None:
        exchange = _exchange()
        with patch.object(
            RevolutXExchange,
            "_request",
            new=AsyncMock(return_value={"data": []}),
        ):
            candles = await exchange.get_candles(symbol="BTC-EUR", timeframe="1h")
        assert candles == []


class TestIterCandlePagesAndBackfill:
    @pytest.mark.asyncio
    async def test_per_page_call_omits_since_ms(self) -> None:
        """Revolut X rejects single requests that would return more than
        ~50,000 rows. Backfill MUST therefore page without ``since`` —
        each page lets the API return its natural 5000-row window
        ending at ``until``. Regression test for the user's reported
        ``no Gradio error: too many rows`` issue."""
        exchange = _exchange()
        page = [
            {"timestamp": 100, "symbol": "BTC-EUR", "timeframe": "1m"} | _ohlcv(),
        ]
        get_candles_mock = AsyncMock(side_effect=[page, []])

        with patch.object(RevolutXExchange, "get_candles", new=get_candles_mock):
            await exchange.backfill_candles(
                symbol="BTC-EUR",
                timeframe="1m",
                since_ms=0,
                until_ms=10_000,
            )

        for call in get_candles_mock.await_args_list:
            assert "since_ms" not in call.kwargs, (
                "backfill_candles must not pass since_ms to per-page calls "
                "— Revolut X rejects ranges that would exceed 50k rows."
            )

    @pytest.mark.asyncio
    async def test_walks_cursor_back_until_since_is_covered(self) -> None:
        """The loop should page successively older windows until the
        earliest candle in a page is at or before ``since_ms``."""
        exchange = _exchange()

        page_a = [
            {"timestamp": 200, "symbol": "BTC-EUR", "timeframe": "1m"} | _ohlcv(),
            {"timestamp": 250, "symbol": "BTC-EUR", "timeframe": "1m"} | _ohlcv(),
        ]
        page_b = [
            {"timestamp": 100, "symbol": "BTC-EUR", "timeframe": "1m"} | _ohlcv(),
            {"timestamp": 150, "symbol": "BTC-EUR", "timeframe": "1m"} | _ohlcv(),
        ]
        get_candles_mock = AsyncMock(side_effect=[page_a, page_b])

        with patch.object(RevolutXExchange, "get_candles", new=get_candles_mock):
            candles = await exchange.backfill_candles(
                symbol="BTC-EUR",
                timeframe="1m",
                since_ms=120,
                until_ms=300,
            )

        # Two pages were fetched and the second cursor walked back below 200.
        assert get_candles_mock.await_count == 2
        second_call = get_candles_mock.await_args_list[1]
        assert second_call.kwargs["until_ms"] == 199

        # Result is filtered to [since_ms, until_ms] and sorted ascending.
        assert [c["timestamp"] for c in candles] == [150, 200, 250]

    @pytest.mark.asyncio
    async def test_stops_on_empty_page(self) -> None:
        exchange = _exchange()
        get_candles_mock = AsyncMock(return_value=[])
        with patch.object(RevolutXExchange, "get_candles", new=get_candles_mock):
            result = await exchange.backfill_candles(
                symbol="BTC-EUR",
                timeframe="1h",
                since_ms=0,
                until_ms=1,
            )
        assert result == []
        get_candles_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_pages_caps_iteration(self) -> None:
        """A misbehaving server that always returns candles after the
        cursor must not loop forever — max_pages bounds the cost."""
        exchange = _exchange()

        def make_page(start_ts: int) -> list[dict]:
            return [
                {
                    "timestamp": start_ts,
                    "symbol": "BTC-EUR",
                    "timeframe": "1m",
                }
                | _ohlcv()
            ]

        cursors_seen: list[int] = []

        async def fake_get_candles(**kwargs: object) -> list[dict]:
            until_ms = int(kwargs["until_ms"])  # type: ignore[arg-type]
            cursors_seen.append(until_ms)
            # Each page returns a single candle whose start is the cursor,
            # so backfill_candles will walk the cursor back forever unless
            # max_pages caps it.
            return make_page(until_ms)

        with patch.object(
            RevolutXExchange, "get_candles", new=AsyncMock(side_effect=fake_get_candles)
        ):
            await exchange.backfill_candles(
                symbol="BTC-EUR",
                timeframe="1m",
                since_ms=-(10**12),  # impossible to reach with one-step cursor
                until_ms=1000,
                max_pages=4,
            )

        # max_pages=4 → exactly four /candles calls.
        assert len(cursors_seen) == 4

    @pytest.mark.asyncio
    async def test_invalid_range_returns_empty(self) -> None:
        exchange = _exchange()
        result = await exchange.backfill_candles(
            symbol="BTC-EUR",
            timeframe="1h",
            since_ms=2000,
            until_ms=1000,
        )
        assert result == []


def _ohlcv() -> dict[str, Decimal]:
    """Tiny helper: a fixed OHLCV body shared by the backfill tests."""
    return {
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("1.5"),
    }
