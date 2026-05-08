"""Tests for :class:`cryptrink.web.live_loop.LiveLoop`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from cryptrink.execution.base import ExecutionResult
from cryptrink.strategies.base import (
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)
from cryptrink.web import live_loop as live_loop_module
from cryptrink.web.live_loop import (
    LiveLoop,
    LiveLoopState,
    get_active_loop,
    reset_active_loop,
    set_active_loop,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Each test starts with no active loop."""
    reset_active_loop()
    yield
    reset_active_loop()


def _make_candle_dicts(count: int = 150, base_price: float = 50000.0) -> list[dict[str, Any]]:
    """Build a list of dict-shaped OHLCV candles compatible with HistoricalDataFeed."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[dict[str, Any]] = []
    for i in range(count):
        ts = start + timedelta(hours=i)
        price = base_price + i
        candles.append(
            {
                "symbol": "BTC-EUR",
                "timeframe": "1h",
                "timestamp": ts,
                "open": Decimal(str(price)),
                "high": Decimal(str(price + 10)),
                "low": Decimal(str(price - 10)),
                "close": Decimal(str(price)),
                "volume": Decimal("1.0"),
            }
        )
    return candles


def _make_strategy(signal_type: SignalType = SignalType.HOLD) -> MagicMock:
    """Mock :class:`BaseStrategy` returning a fixed signal."""
    strategy = MagicMock()
    strategy.name = "fake_strategy"
    strategy.timeframe = "1h"
    strategy.required_history = 50

    def gen(ctx: StrategyContext) -> Signal:
        return Signal(
            signal_type=signal_type,
            symbol=ctx.symbol,
            strength=SignalStrength.STRONG,
            timestamp=ctx.timestamp,
            price=ctx.current_price,
        )

    strategy.generate_signal = gen
    return strategy


def _make_engine(success: bool = True, order_id: str | None = "ORD-1") -> MagicMock:
    """Mock :class:`TradingEngine.process_signal`."""
    engine = MagicMock()
    engine.process_signal = AsyncMock(
        return_value=ExecutionResult(success=success, message="ok", order_id=order_id)
    )
    return engine


def _make_data_feed(candles: list[dict[str, Any]] | None = None) -> MagicMock:
    feed = MagicMock()
    feed.get_ohlcv = AsyncMock(return_value=candles if candles is not None else [])
    return feed


class TestLiveLoopValidation:
    def test_rejects_non_positive_interval(self) -> None:
        with pytest.raises(ValueError, match="interval_seconds must be positive"):
            LiveLoop(
                engine=_make_engine(),
                strategy=_make_strategy(),
                symbol="BTC-EUR",
                data_feed=_make_data_feed(),
                interval_seconds=0,
            )


class TestLiveLoopLifecycle:
    async def test_start_is_idempotent(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
        )
        await loop.start()
        first_task = loop._task
        await loop.start()  # second call must not spawn a second task
        assert loop._task is first_task
        await loop.stop()

    async def test_stop_without_start_is_noop(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
        )
        await loop.stop()  # must not raise
        assert not loop.is_running

    async def test_snapshot_reports_running_state(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
        )
        assert loop.snapshot().running is False
        await loop.start()
        assert loop.snapshot().running is True
        await loop.stop()
        snap = loop.snapshot()
        assert snap.running is False
        assert snap.stopped_at is not None


class TestLiveLoopIteration:
    async def test_iterate_with_no_data_increments_iteration_only(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed([]),
            interval_seconds=60,
        )
        await loop._iterate_once()
        snap = loop.snapshot()
        assert snap.iteration_count == 1
        assert snap.signal_count == 0
        assert snap.execution_count == 0

    async def test_hold_signal_does_not_count_as_signal(self) -> None:
        engine = _make_engine(success=True, order_id=None)
        loop = LiveLoop(
            engine=engine,
            strategy=_make_strategy(SignalType.HOLD),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(_make_candle_dicts()),
            interval_seconds=60,
        )
        await loop._iterate_once()
        engine.process_signal.assert_awaited_once()
        snap = loop.snapshot()
        assert snap.iteration_count == 1
        assert snap.signal_count == 0
        assert snap.last_signal_type is None

    async def test_entry_long_increments_signal_and_execution(self) -> None:
        engine = _make_engine(success=True, order_id="ORD-1")
        loop = LiveLoop(
            engine=engine,
            strategy=_make_strategy(SignalType.ENTRY_LONG),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(_make_candle_dicts()),
            interval_seconds=60,
        )
        await loop._iterate_once()
        snap = loop.snapshot()
        assert snap.signal_count == 1
        assert snap.execution_count == 1
        assert snap.last_signal_type == SignalType.ENTRY_LONG.value

    async def test_routes_signal_through_engine_with_signal_kwarg(self) -> None:
        engine = _make_engine()
        candles = _make_candle_dicts()
        loop = LiveLoop(
            engine=engine,
            strategy=_make_strategy(SignalType.ENTRY_LONG),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(candles),
            interval_seconds=60,
        )
        await loop._iterate_once()

        engine.process_signal.assert_awaited_once()
        kwargs = engine.process_signal.await_args.kwargs
        assert kwargs["symbol"] == "BTC-EUR"
        assert kwargs["current_price"] == Decimal(str(candles[-1]["close"]))
        assert kwargs["signal"].signal_type is SignalType.ENTRY_LONG
        assert isinstance(kwargs["timestamp"], datetime)


class TestLiveLoopErrors:
    async def test_iteration_error_records_state_and_continues(self) -> None:
        engine = _make_engine()
        engine.process_signal = AsyncMock(side_effect=RuntimeError("boom"))
        loop = LiveLoop(
            engine=engine,
            strategy=_make_strategy(SignalType.ENTRY_LONG),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(_make_candle_dicts()),
            interval_seconds=0.05,
        )
        await loop.start()
        await asyncio.sleep(0.15)
        await loop.stop()
        snap = loop.snapshot()
        assert snap.error_count >= 1
        assert snap.last_error is not None
        assert "boom" in snap.last_error


class TestActiveLoopRegistry:
    def test_get_active_loop_returns_none_initially(self) -> None:
        assert get_active_loop() is None

    async def test_set_and_clear_active_loop(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
        )
        set_active_loop(loop)
        assert get_active_loop() is loop
        live_loop_module.reset_active_loop()
        assert get_active_loop() is None


class TestStopCallback:
    async def test_on_stop_runs_after_task_joins(self) -> None:
        on_stop = AsyncMock()
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_stop=on_stop,
        )
        await loop.start()
        await loop.stop()
        on_stop.assert_awaited_once()

    async def test_on_stop_exception_does_not_break_stop(self) -> None:
        async def failing_stop() -> None:
            raise RuntimeError("cleanup boom")

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_stop=failing_stop,
        )
        await loop.start()
        await loop.stop()  # must not raise
        assert not loop.is_running

    async def test_on_stop_skipped_when_never_started(self) -> None:
        on_stop = AsyncMock()
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_stop=on_stop,
        )
        await loop.stop()
        on_stop.assert_not_awaited()


class TestSignalCallback:
    async def test_callback_receives_signal_and_result(self) -> None:
        observed: list[tuple[Signal, ExecutionResult]] = []

        async def on_signal(signal: Signal, result: ExecutionResult) -> None:
            observed.append((signal, result))

        engine = _make_engine(order_id="ORD-2")
        loop = LiveLoop(
            engine=engine,
            strategy=_make_strategy(SignalType.ENTRY_LONG),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(_make_candle_dicts()),
            interval_seconds=60,
            on_signal=on_signal,
        )
        await loop._iterate_once()
        assert len(observed) == 1
        assert observed[0][0].signal_type is SignalType.ENTRY_LONG
        assert observed[0][1].order_id == "ORD-2"

    async def test_callback_exception_does_not_kill_iteration(self) -> None:
        async def on_signal(*_: object) -> None:
            raise RuntimeError("callback boom")

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(SignalType.ENTRY_LONG),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(_make_candle_dicts()),
            interval_seconds=60,
            on_signal=on_signal,
        )
        await loop._iterate_once()  # must not raise
        assert loop.snapshot().iteration_count == 1


# Sanity import to ensure pandas is available (the indicators helper requires it).
def test_pandas_is_imported() -> None:
    assert pd.__version__ is not None


class TestHeartbeatCallback:
    """The heartbeat task fires ``on_heartbeat(state)`` every
    ``heartbeat_interval_seconds`` seconds, independent of the iteration
    cadence. A misbehaving heartbeat callback must not stall the trading
    loop, and ``stop()`` must drain the heartbeat task cleanly."""

    async def test_heartbeat_fires_after_each_interval(self) -> None:
        observed: list[LiveLoopState] = []

        async def on_heartbeat(state: LiveLoopState) -> None:
            observed.append(state)

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_heartbeat=on_heartbeat,
            heartbeat_interval_seconds=0.05,
        )
        await loop.start()
        # Three intervals at 50ms ≈ 150ms; allow margin so CI doesn't
        # flake. The heartbeat sleeps before the first beat.
        await asyncio.sleep(0.18)
        await loop.stop()
        assert len(observed) >= 2
        # Each heartbeat receives a LiveLoopState with the symbol set.
        assert all(s.symbol == "BTC-EUR" for s in observed)

    async def test_callback_failure_does_not_kill_heartbeat_task(self) -> None:
        calls = 0

        async def on_heartbeat(_: LiveLoopState) -> None:
            nonlocal calls
            calls += 1
            # First call raises, subsequent ones return normally. The
            # contract is "an exception in one callback must not kill
            # later ones" — proven by reaching call #2 at all.
            if calls == 1:
                raise RuntimeError("webhook went sideways")

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_heartbeat=on_heartbeat,
            heartbeat_interval_seconds=0.05,
        )
        await loop.start()
        # Generous timeout: ``logger.exception``'s Rich rendering can take
        # ~100ms per call under pytest, so we don't gamble on tight windows.
        await asyncio.sleep(0.6)
        await loop.stop()
        assert calls >= 2, f"heartbeat task died after first exception (calls={calls})"

    async def test_no_heartbeat_task_when_callback_missing(self) -> None:
        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_heartbeat=None,
            heartbeat_interval_seconds=0.05,
        )
        await loop.start()
        # No callback ⇒ no heartbeat task spawned.
        assert loop._heartbeat_task is None
        await loop.stop()

    async def test_no_heartbeat_task_when_interval_missing(self) -> None:
        async def on_heartbeat(_: LiveLoopState) -> None:
            pass

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_heartbeat=on_heartbeat,
            heartbeat_interval_seconds=None,
        )
        await loop.start()
        assert loop._heartbeat_task is None
        await loop.stop()

    async def test_rejects_non_positive_heartbeat_interval(self) -> None:
        async def on_heartbeat(_: LiveLoopState) -> None:
            pass

        with pytest.raises(ValueError, match="heartbeat_interval_seconds"):
            LiveLoop(
                engine=_make_engine(),
                strategy=_make_strategy(),
                symbol="BTC-EUR",
                data_feed=_make_data_feed(),
                interval_seconds=60,
                on_heartbeat=on_heartbeat,
                heartbeat_interval_seconds=0,
            )

    async def test_stop_drains_heartbeat_task(self) -> None:
        """``stop()`` must wait for the heartbeat task to finish — a
        slow webhook in flight gets up to 5 s, then is cancelled. A
        leaked heartbeat task would log warnings forever after stop."""

        async def on_heartbeat(_: LiveLoopState) -> None:
            return None

        loop = LiveLoop(
            engine=_make_engine(),
            strategy=_make_strategy(),
            symbol="BTC-EUR",
            data_feed=_make_data_feed(),
            interval_seconds=60,
            on_heartbeat=on_heartbeat,
            heartbeat_interval_seconds=0.05,
        )
        await loop.start()
        await asyncio.sleep(0.05)
        await loop.stop()
        assert loop._heartbeat_task is None
