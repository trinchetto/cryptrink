"""Background loop that drives a strategy through :class:`TradingEngine`.

The loop is the engine of cryptrink's live tab: every ``interval_seconds``
it pulls the latest OHLCV for the configured symbol, asks the strategy
for a :class:`Signal`, and routes that signal through the trading engine
so risk validation, the configured executor, and persistence all run.

The class itself is deliberately I/O-shape agnostic — it talks to a
:class:`HistoricalDataFeed`, a :class:`BaseStrategy`, and a
:class:`TradingEngine` and nothing else. The Gradio Live tab wires those
collaborators (paper or live executor, in-memory or persistent DB, …)
based on the current settings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.data.indicators import ohlcv_to_dataframe
from cryptrink.strategies.base import SignalType, StrategyContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cryptrink.data.feed import BaseDataFeed
    from cryptrink.execution.base import ExecutionResult
    from cryptrink.execution.engine import TradingEngine
    from cryptrink.strategies.base import BaseStrategy, Signal

logger = get_logger(__name__)


@dataclass(frozen=True)
class LiveLoopState:
    """Immutable snapshot of a :class:`LiveLoop` for UI rendering."""

    running: bool = False
    symbol: str | None = None
    strategy_name: str | None = None
    interval_seconds: float = 60.0
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_iteration_at: datetime | None = None
    last_signal_at: datetime | None = None
    last_signal_type: str | None = None
    iteration_count: int = 0
    signal_count: int = 0
    execution_count: int = 0
    error_count: int = 0
    last_error: str | None = None


@dataclass
class _MutableState:
    """Internal mutable mirror of :class:`LiveLoopState`."""

    running: bool = False
    symbol: str | None = None
    strategy_name: str | None = None
    interval_seconds: float = 60.0
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_iteration_at: datetime | None = None
    last_signal_at: datetime | None = None
    last_signal_type: str | None = None
    iteration_count: int = 0
    signal_count: int = 0
    execution_count: int = 0
    error_count: int = 0
    last_error: str | None = None

    def snapshot(self) -> LiveLoopState:
        return LiveLoopState(**self.__dict__)


class LiveLoop:
    """Run a strategy + :class:`TradingEngine` on a periodic interval.

    Lifecycle::

        loop = LiveLoop(engine, strategy, symbol="BTC-EUR",
                        data_feed=feed, interval_seconds=60)
        await loop.start()   # spawns asyncio.Task
        ...                  # operator inspects loop.snapshot() in the UI
        await loop.stop()    # signals cancellation and awaits clean exit

    ``start()`` and ``stop()`` are both idempotent. After ``stop()`` the
    same instance can be started again, but the Gradio tab builds a fresh
    instance per Start click so strategy/symbol changes take effect.

    The loop swallows exceptions inside each iteration — a transient
    network blip should not kill the background task. Errors increment
    ``error_count`` and are exposed via :attr:`snapshot` so the UI can
    surface them.
    """

    def __init__(
        self,
        *,
        engine: TradingEngine,
        strategy: BaseStrategy,
        symbol: str,
        data_feed: BaseDataFeed,
        interval_seconds: float = 60.0,
        on_signal: Callable[[Signal, ExecutionResult], Awaitable[None]] | None = None,
        on_stop: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            msg = f"interval_seconds must be positive, got {interval_seconds}"
            raise ValueError(msg)

        self._engine = engine
        self._strategy = strategy
        self._symbol = symbol
        self._data_feed = data_feed
        self._interval_seconds = interval_seconds
        self._on_signal = on_signal
        self._on_stop = on_stop

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._state = _MutableState(
            symbol=symbol,
            strategy_name=getattr(strategy, "name", strategy.__class__.__name__),
            interval_seconds=interval_seconds,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Spawn the background task. Idempotent."""
        if self._task is not None and not self._task.done():
            return

        self._stop_event.clear()
        self._state.running = True
        self._state.started_at = datetime.now(UTC)
        self._state.stopped_at = None
        self._state.last_error = None
        self._task = asyncio.create_task(self._run_loop(), name=f"live-loop:{self._symbol}")
        logger.info(
            "live_loop_started",
            symbol=self._symbol,
            strategy=self._state.strategy_name,
            interval_seconds=self._interval_seconds,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and await termination. Idempotent.

        After the background task has joined, the optional ``on_stop``
        callback runs so callers can release exchange clients, close
        notifier sessions, etc. Callback failures are logged but never
        propagated — :meth:`stop` always returns cleanly so the UI can
        re-enable controls.
        """
        if self._task is None:
            self._state.running = False
            return

        self._stop_event.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._state.running = False
            self._state.stopped_at = datetime.now(UTC)

        if self._on_stop is not None:
            try:
                await self._on_stop()
            except Exception:
                logger.exception("live_loop_on_stop_failed", symbol=self._symbol)

        logger.info(
            "live_loop_stopped",
            symbol=self._symbol,
            iteration_count=self._state.iteration_count,
            signal_count=self._state.signal_count,
            error_count=self._state.error_count,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def snapshot(self) -> LiveLoopState:
        """Return an immutable view of the loop's current state."""
        return self._state.snapshot()

    @property
    def is_running(self) -> bool:
        """True while the asyncio task is alive."""
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._iterate_once()
            except Exception as exc:
                self._state.error_count += 1
                self._state.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "live_loop_iteration_failed",
                    symbol=self._symbol,
                )

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
                return  # stop signal received during sleep
            except TimeoutError:
                continue

    async def _iterate_once(self) -> None:
        candles = await self._data_feed.get_ohlcv(
            symbol=self._symbol,
            timeframe=self._strategy.timeframe,
            limit=max(self._strategy.required_history + 10, 100),
        )
        self._state.last_iteration_at = datetime.now(UTC)
        self._state.iteration_count += 1

        if not candles:
            return

        ohlcv_df = ohlcv_to_dataframe(candles)
        last_index = ohlcv_df.index[-1]
        candle_ts = (
            last_index.to_pydatetime()
            if hasattr(last_index, "to_pydatetime")
            else datetime.now(UTC)
        )
        if candle_ts.tzinfo is None:
            candle_ts = candle_ts.replace(tzinfo=UTC)
        current_price = Decimal(str(ohlcv_df.iloc[-1]["close"]))

        context = StrategyContext(
            symbol=self._symbol,
            current_price=current_price,
            timestamp=candle_ts,
            ohlcv=ohlcv_df,
        )
        signal = self._strategy.generate_signal(context)
        result = await self._engine.process_signal(
            symbol=self._symbol,
            current_price=current_price,
            timestamp=candle_ts,
            signal=signal,
        )

        if signal.signal_type != SignalType.HOLD:
            self._state.last_signal_at = candle_ts
            self._state.last_signal_type = signal.signal_type.value
            self._state.signal_count += 1
        if result.success and result.order_id is not None:
            self._state.execution_count += 1

        if self._on_signal is not None:
            try:
                await self._on_signal(signal, result)
            except Exception:
                logger.exception("live_loop_callback_failed", symbol=self._symbol)


# ----------------------------------------------------------------------
# Module-level singleton — the Live tab keeps at most one loop active.
# ----------------------------------------------------------------------
_active_loop: LiveLoop | None = None


def get_active_loop() -> LiveLoop | None:
    """Return the currently-registered :class:`LiveLoop`, if any."""
    return _active_loop


def set_active_loop(loop: LiveLoop | None) -> None:
    """Register (or clear) the singleton :class:`LiveLoop`."""
    global _active_loop
    _active_loop = loop


def reset_active_loop() -> None:
    """Forget the singleton without stopping it.

    Used by tests to isolate module-level state between cases.
    """
    set_active_loop(None)


__all__ = [
    "LiveLoop",
    "LiveLoopState",
    "get_active_loop",
    "reset_active_loop",
    "set_active_loop",
]
