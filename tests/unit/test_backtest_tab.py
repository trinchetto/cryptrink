"""Tests for the Backtest tab's pure helpers.

We don't try to exercise the full Gradio handler here — that requires a
live Blocks context and an async event loop coordinated with the
streaming run. Instead we pin the small, easy-to-regress pieces:

* ``_subsample`` — caps a DataFrame at ``_PLOT_MAX_POINTS``, preserves
  the first and last row so the chart x-axis spans the full window.
* ``autofill_dates`` — when the operator picks a dataset, snap Start /
  End to its earliest / latest date.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.data.storage import OHLCVRepository
from cryptrink.runtime import build_session_factory
from cryptrink.web import state as web_state
from cryptrink.web.state import WebRuntime, reset_runtime
from cryptrink.web.tabs.backtest import _PLOT_MAX_POINTS, _subsample, autofill_dates


@pytest.fixture(autouse=True)
def _isolate() -> None:
    reset_runtime()
    yield
    reset_runtime()


def _install_runtime() -> WebRuntime:
    settings = Settings(
        revolutx=RevolutXSettings(),
        risk=RiskSettings(),
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        notifications=NotificationSettings(),
    )
    runtime = WebRuntime(
        settings=settings,
        session_factory=build_session_factory(settings.database.url),
    )
    web_state._runtime = runtime
    return runtime


class TestSubsample:
    def test_no_op_when_under_threshold(self) -> None:
        df = pd.DataFrame({"timestamp": list(range(100)), "y": list(range(100))})
        sampled = _subsample(df, max_points=500)
        assert len(sampled) == 100  # unchanged
        assert sampled.iloc[0]["timestamp"] == 0
        assert sampled.iloc[-1]["timestamp"] == 99

    def test_caps_to_max_points(self) -> None:
        df = pd.DataFrame({"timestamp": list(range(10_000)), "y": list(range(10_000))})
        sampled = _subsample(df, max_points=500)
        # We pick a stride and may append the final row, so the result is
        # close to but never wildly above max_points.
        assert len(sampled) <= 502

    def test_preserves_first_and_last_row(self) -> None:
        """A reader who looks at the chart's x-axis range should see the
        full span — without this guarantee the chart would silently lose
        either end of the backtest window."""
        df = pd.DataFrame({"timestamp": list(range(10_000)), "y": list(range(10_000))})
        sampled = _subsample(df, max_points=500)
        assert sampled.iloc[0]["timestamp"] == 0
        assert sampled.iloc[-1]["timestamp"] == 9_999

    def test_default_max_points_is_500(self) -> None:
        # The constant is part of the visual contract of the tab — the
        # value is chosen empirically and should be visible in code.
        assert _PLOT_MAX_POINTS == 500


class TestAutofillDates:
    @pytest.mark.asyncio
    async def test_returns_no_change_when_dataset_value_blank(self) -> None:
        start, end = await autofill_dates("")
        # Both should be no-op gradio updates (we just confirm they're
        # not strings — gr.update() returns a dict-like, not a date).
        assert not isinstance(start, str)
        assert not isinstance(end, str)

    @pytest.mark.asyncio
    async def test_returns_no_change_for_unparseable_value(self) -> None:
        start, end = await autofill_dates("totally-not-a-dataset-value")
        assert not isinstance(start, str)
        assert not isinstance(end, str)

    @pytest.mark.asyncio
    async def test_snaps_dates_to_dataset_range(self) -> None:
        runtime = _install_runtime()
        from cryptrink.cli.utils import init_db_schema

        await init_db_schema(runtime.session_factory)
        repo = OHLCVRepository(runtime.session_factory)
        # 3 candles spanning 2024-03-01 → 2024-05-15.
        await repo.save_batch(
            [
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": int(datetime(2024, 3, 1, tzinfo=UTC).timestamp() * 1000),
                    "open": Decimal("100"),
                    "high": Decimal("105"),
                    "low": Decimal("95"),
                    "close": Decimal("100"),
                    "volume": Decimal("1"),
                },
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": int(datetime(2024, 4, 1, tzinfo=UTC).timestamp() * 1000),
                    "open": Decimal("100"),
                    "high": Decimal("105"),
                    "low": Decimal("95"),
                    "close": Decimal("100"),
                    "volume": Decimal("1"),
                },
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": int(datetime(2024, 5, 15, tzinfo=UTC).timestamp() * 1000),
                    "open": Decimal("100"),
                    "high": Decimal("105"),
                    "low": Decimal("95"),
                    "close": Decimal("100"),
                    "volume": Decimal("1"),
                },
            ]
        )
        start, end = await autofill_dates("BTC-EUR|1h")
        # gr.update returns a dict — assert the date strings appear in it.
        assert isinstance(start, dict)
        assert isinstance(end, dict)
        assert start.get("value") == "2024-03-01"
        assert end.get("value") == "2024-05-15"
