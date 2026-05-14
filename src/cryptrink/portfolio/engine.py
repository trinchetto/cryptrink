"""Event-driven backtest engine for portfolios.

Mirrors :class:`cryptrink.backtest.engine.BacktestEngine` but iterates
over multiple symbols on a shared bar clock with a single
:class:`TradingEngine` and a single :class:`BacktestExecutor` (one cash
pool, one risk validator, one position view).

Phase 1 constraints:

* All allocations share the same timeframe (validated against the
  portfolio config).
* The bar clock is the **intersection** of every symbol's timestamp
  set inside the backtest window. If pair A is missing the bar at
  ``T``, the engine skips ``T`` for *every* allocation rather than
  forward-filling. The alternative — running each pair on its own
  timestamps — would interleave orders unpredictably and make per-bar
  mark-to-market hard to reason about.
* Position sizing falls back to the executor's default 10%-of-cash
  rule. The portfolio-level ``weight`` field is recorded in the YAML
  config but does not yet drive sizing; that lands in Phase 1.5.

Per-allocation strategy state (e.g. SMA crossover's ``_prev_*`` cache)
is owned by the per-allocation strategy instance held inside the
:class:`PortfolioStrategyRouter`, so each allocation's signals depend
only on its own pair's history — exactly as in the single-symbol
backtester.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cryptrink.backtest.executor import BacktestExecutor
from cryptrink.backtest.metrics import BacktestMetricsCalculator
from cryptrink.backtest.models import ConstantSlippageModel, PercentageFeeModel
from cryptrink.core.logging import get_logger
from cryptrink.execution.engine import TradingEngine
from cryptrink.portfolio.result import AllocationBreakdown, PortfolioBacktestResult
from cryptrink.portfolio.router import PortfolioStrategyRouter
from cryptrink.runtime import ensure_builtins_registered
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)

if TYPE_CHECKING:
    from cryptrink.core.config import RiskSettings
    from cryptrink.data.feed import HistoricalDataFeed
    from cryptrink.execution.models import Position
    from cryptrink.portfolio.models import Portfolio

logger = get_logger(__name__)


# Same map BacktestEngine uses; duplicated rather than imported to keep
# the portfolio module's dependencies pointed forward (engine ← portfolio,
# never the other way around).
_TIMEFRAME_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


class PortfolioBacktestEngine:
    """Drive N strategies through one shared :class:`TradingEngine`."""

    def __init__(
        self,
        portfolio: Portfolio,
        data_feed: HistoricalDataFeed,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        slippage_bps: Decimal = Decimal("0.0005"),
        fee_pct: Decimal = Decimal("0.0009"),
        risk_settings: RiskSettings | None = None,
    ) -> None:
        errors = portfolio.validate()
        if errors:
            raise ValueError("Invalid portfolio: " + "; ".join(errors))

        self._portfolio = portfolio
        self._data_feed = data_feed
        self._initial_balance = portfolio.initial_balance

        # Build per-allocation strategies via the registry. Keying by
        # symbol works because the validator already rejected duplicate
        # symbols in enabled allocations.
        ensure_builtins_registered()
        strategies: dict[str, BaseStrategy] = {}
        for alloc in portfolio.enabled_allocations():
            strategies[alloc.symbol] = strategy_registry.create(alloc.strategy_name, **alloc.params)
        self._router = PortfolioStrategyRouter(strategies, portfolio_name=portfolio.name)

        # Shared executor + trading engine — one cash pool across pairs.
        self._slippage_model = ConstantSlippageModel(slippage_bps=slippage_bps)
        self._fee_model = PercentageFeeModel(fee_pct=fee_pct)
        self._executor = BacktestExecutor(
            initial_balance=portfolio.initial_balance,
            slippage_model=self._slippage_model,
            fee_model=self._fee_model,
        )

        if session_factory is None:
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            session_factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            self._owns_session_factory = True
            self._session_factory = session_factory
        else:
            self._owns_session_factory = False
            self._session_factory = session_factory

        self._engine = TradingEngine(
            strategy=self._router,
            executor=self._executor,
            session_factory=self._session_factory,
            initial_balance=portfolio.initial_balance,
            risk_settings=risk_settings,
        )

        self._metrics_calculator = BacktestMetricsCalculator()
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        # Diagnostic counters used by the UI to log per-allocation
        # signal histograms after the run.
        self._signal_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        logger.info(
            "portfolio_backtest_engine_initialized",
            portfolio=portfolio.name,
            timeframe=portfolio.timeframe,
            initial_balance=float(portfolio.initial_balance),
            allocations=len(portfolio.enabled_allocations()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        start_time: datetime,
        end_time: datetime,
        lookback_periods: int = 200,
    ) -> PortfolioBacktestResult:
        """Run the portfolio backtest and return aggregate + per-pair results."""
        timeframe = self._portfolio.timeframe
        if timeframe not in _TIMEFRAME_TO_DELTA:
            raise ValueError(f"Unsupported timeframe {timeframe!r}")

        if self._owns_session_factory:
            await self._initialize_database()

        lookback_start = self._calculate_lookback_start(start_time, timeframe, lookback_periods)

        # 1. Load OHLCV per symbol → frame keyed by datetime.
        frames: dict[str, pd.DataFrame] = {}
        for symbol in self._router.symbols:
            ohlcv_data = await self._data_feed.get_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                start_time=lookback_start,
                end_time=end_time,
                limit=10_000_000,
            )
            if not ohlcv_data:
                raise ValueError(
                    f"No historical data for {symbol} {timeframe} between "
                    f"{lookback_start.isoformat()} and {end_time.isoformat()}. "
                    "Backfill it from the Data tab before running."
                )
            frames[symbol] = self._build_dataframe(ohlcv_data)

        # 2. Build the shared bar clock as the *intersection* of every
        #    symbol's index inside the backtest window. Allocations that
        #    have a candle gap drag the whole portfolio over that gap;
        #    we trade reduced sample size for a deterministic, easy-to-
        #    reason-about per-bar invariant.
        common_index = self._intersect_indices(frames, start_time, end_time)
        if not common_index:
            raise ValueError(
                "No timestamps are common to every allocation in the requested "
                f"window ({start_time.isoformat()} → {end_time.isoformat()}). "
                "Backfill the missing pairs or shorten the window."
            )

        logger.info(
            "portfolio_data_loaded",
            symbols=list(frames),
            common_bars=len(common_index),
            window_start=common_index[0].isoformat(),
            window_end=common_index[-1].isoformat(),
        )

        # 3. Seed the equity curve at the requested start.
        self._equity_curve.append((start_time, self._initial_balance))

        # 4. Event-by-event replay.
        for ts in common_index:
            for symbol, frame in frames.items():
                # ``loc[:ts]`` slices the DatetimeIndex up to and
                # including ``ts``. pandas-stubs is over-conservative
                # about datetime slicing here — at runtime this is the
                # documented behaviour for DatetimeIndex.
                history = frame.loc[:ts]  # type: ignore[misc]
                strategy_context = self._build_strategy_context(symbol, history)
                signal = self._router.generate_signal(strategy_context)
                self._signal_counts[symbol][signal.signal_type.value] += 1

                self._router.set_active_symbol(symbol)
                await self._engine.process_signal(
                    symbol=symbol,
                    current_price=strategy_context.current_price,
                    timestamp=ts,
                    signal=signal,
                )

            # Mark the portfolio to market once per bar across every
            # symbol — cash + sum(open position * latest close).
            self._equity_curve.append((ts, self._mark_to_market_equity(frames, ts)))

        # 5. Unwind any positions still open at the end of the window.
        last_ts = common_index[-1]
        for symbol, frame in frames.items():
            position = self._executor.get_position(symbol)
            if position is None:
                continue
            final_price = Decimal(str(frame.loc[last_ts, "close"]))  # type: ignore[index]
            await self._close_position(symbol, final_price, end_time)

        # 6. Append the final cash equity post-unwind so the curve's
        #    right edge agrees with the metrics table to the cent.
        self._equity_curve.append((end_time, self._executor.balance))

        return await self._calculate_results(start_time, end_time)

    @property
    def signal_counts(self) -> dict[str, dict[str, int]]:
        """Per-allocation histogram of emitted signal types."""
        return {sym: dict(counts) for sym, counts in self._signal_counts.items()}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _initialize_database(self) -> None:
        from cryptrink.execution.models import Position

        engine = self._session_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.run_sync(Position.metadata.create_all)

    @staticmethod
    def _calculate_lookback_start(
        start_time: datetime, timeframe: str, lookback_periods: int
    ) -> datetime:
        delta = _TIMEFRAME_TO_DELTA[timeframe]
        return start_time - (delta * lookback_periods)

    @staticmethod
    def _build_dataframe(ohlcv_data: list[dict[str, object]]) -> pd.DataFrame:
        timestamps: list[datetime] = []
        for candle in ohlcv_data:
            value = candle["timestamp"]
            if isinstance(value, datetime):
                timestamps.append(value if value.tzinfo is not None else value.replace(tzinfo=UTC))
            elif isinstance(value, (int, float)):
                timestamps.append(datetime.fromtimestamp(int(value) / 1000, tz=UTC))
            else:
                raise TypeError(f"Unsupported candle timestamp type: {type(value).__name__}")
        df = pd.DataFrame(
            {
                "open": [float(c["open"]) for c in ohlcv_data],  # type: ignore[arg-type]
                "high": [float(c["high"]) for c in ohlcv_data],  # type: ignore[arg-type]
                "low": [float(c["low"]) for c in ohlcv_data],  # type: ignore[arg-type]
                "close": [float(c["close"]) for c in ohlcv_data],  # type: ignore[arg-type]
                "volume": [float(c["volume"]) for c in ohlcv_data],  # type: ignore[arg-type]
            },
            index=pd.DatetimeIndex(timestamps, name="timestamp"),
        )
        return df

    @staticmethod
    def _intersect_indices(
        frames: dict[str, pd.DataFrame],
        start_time: datetime,
        end_time: datetime,
    ) -> list[datetime]:
        """Intersect every frame's DatetimeIndex inside the window."""
        common: pd.DatetimeIndex | None = None
        for frame in frames.values():
            # The ``DatetimeIndex >= datetime`` comparison narrows the
            # frame's index to the window. pandas-stubs typed ``Index``
            # rather than ``DatetimeIndex`` here so we cast.
            in_window: pd.DatetimeIndex = frame.index[  # type: ignore[assignment]
                (frame.index >= start_time) & (frame.index <= end_time)
            ]
            common = in_window if common is None else common.intersection(in_window)
        if common is None or common.empty:
            return []
        # ``DatetimeIndex.tolist()`` returns ``Timestamp`` instances; the
        # rest of the pipeline expects stdlib ``datetime`` because
        # ``StrategyContext`` is annotated with that and downstream
        # serialisers (BacktestResult, position rows) compare against
        # ``datetime``.
        return [ts.to_pydatetime() for ts in common.sort_values()]

    def _build_strategy_context(self, symbol: str, history: pd.DataFrame) -> StrategyContext:
        from cryptrink.exchange.base import OrderSide

        current_price = Decimal(str(history.iloc[-1]["close"]))
        position = self._executor.get_position(symbol)
        position_size = Decimal("0")
        position_side: OrderSide | None = None
        if position is not None:
            position_size = Decimal(str(position.get("quantity", "0")))
            side_str = position.get("side")
            if side_str == "long":
                position_side = OrderSide.BUY
            elif side_str == "short":
                position_side = OrderSide.SELL

        ts = history.index[-1]
        timestamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        return StrategyContext(
            symbol=symbol,
            current_price=current_price,
            timestamp=timestamp,
            ohlcv=history,
            position_size=position_size,
            position_side=position_side,
        )

    def _mark_to_market_equity(self, frames: dict[str, pd.DataFrame], ts: datetime) -> Decimal:
        """Cash + sum of every open position priced at ``ts``."""
        equity = self._executor.balance
        for symbol, frame in frames.items():
            position = self._executor.get_position(symbol)
            if position is None:
                continue
            quantity = Decimal(str(position.get("quantity", "0")))
            close = Decimal(str(frame.loc[ts, "close"]))  # type: ignore[index]
            equity += quantity * close
        return equity

    async def _close_position(
        self, symbol: str, current_price: Decimal, timestamp: datetime
    ) -> None:
        """Force-close any position still open on ``symbol``."""
        position = self._executor.get_position(symbol)
        if position is None:
            return

        logger.info(
            "portfolio_closing_position_at_end",
            symbol=symbol,
            quantity=str(position.get("quantity", "0")),
            price=str(current_price),
        )

        exit_signal = Signal(
            signal_type=SignalType.EXIT_LONG,
            symbol=symbol,
            timestamp=timestamp,
            price=current_price,
            strength=SignalStrength.STRONG,
        )
        # ``set_active_symbol`` makes sure ``_record_execution`` writes
        # the right strategy_name on the closing position row.
        self._router.set_active_symbol(symbol)
        await self._engine.process_signal(
            symbol=symbol,
            current_price=current_price,
            timestamp=timestamp,
            signal=exit_signal,
        )

    async def _calculate_results(
        self, start_time: datetime, end_time: datetime
    ) -> PortfolioBacktestResult:
        from sqlalchemy import select

        from cryptrink.execution.models import Order, Position

        async with self._session_factory() as session:
            positions_result = await session.execute(
                select(Position).where(Position.status == "closed")
            )
            positions = list(positions_result.scalars().all())
            orders_result = await session.execute(select(Order))
            orders = list(orders_result.scalars().all())

        final_balance = self._executor.balance
        metrics = self._metrics_calculator.calculate(
            positions=positions,
            orders=orders,
            initial_balance=self._initial_balance,
            final_balance=final_balance,
            start_time=start_time,
            end_time=end_time,
            equity_curve=self._equity_curve,
        )

        drawdown_curve = self._calculate_drawdown_curve(self._equity_curve)
        breakdown = self._build_allocation_breakdown(positions)

        return PortfolioBacktestResult(
            portfolio=self._portfolio,
            start_time=start_time,
            end_time=end_time,
            initial_balance=self._initial_balance,
            metrics=metrics,
            equity_curve=self._equity_curve,
            drawdown_curve=drawdown_curve,
            trades=positions,
            orders=orders,
            allocations=breakdown,
        )

    def _build_allocation_breakdown(self, positions: list[Position]) -> list[AllocationBreakdown]:
        """Group closed positions by symbol and roll up per-allocation P&L."""
        by_symbol: dict[str, list[Position]] = defaultdict(list)
        for pos in positions:
            by_symbol[pos.symbol].append(pos)

        breakdown: list[AllocationBreakdown] = []
        for alloc in self._portfolio.enabled_allocations():
            symbol_positions = by_symbol.get(alloc.symbol, [])
            pnls = [Decimal(str(p.realized_pnl)) for p in symbol_positions]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            total = len(symbol_positions)
            win_rate = Decimal(str(len(wins) / total)) if total > 0 else Decimal("0")
            best = max(pnls) if pnls else Decimal("0")
            worst = min(pnls) if pnls else Decimal("0")
            breakdown.append(
                AllocationBreakdown(
                    symbol=alloc.symbol,
                    strategy_name=alloc.strategy_name,
                    realized_pnl=sum(pnls, Decimal("0")),
                    total_trades=total,
                    winning_trades=len(wins),
                    losing_trades=len(losses),
                    win_rate=win_rate,
                    best_trade=best,
                    worst_trade=worst,
                )
            )
        return breakdown

    @staticmethod
    def _calculate_drawdown_curve(
        equity_curve: list[tuple[datetime, Decimal]],
    ) -> list[tuple[datetime, Decimal]]:
        if len(equity_curve) < 2:
            return []
        out: list[tuple[datetime, Decimal]] = []
        peak = equity_curve[0][1]
        for ts, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else Decimal("0")
            out.append((ts, dd))
        return out
