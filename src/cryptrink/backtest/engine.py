"""Backtest engine - orchestrates event-driven historical data replay.

This module provides the main BacktestEngine class that coordinates:
- Historical OHLCV data loading with lookback period
- Event-driven candle-by-candle replay
- Rolling StrategyContext building for strategy signal generation
- Integration with TradingEngine for order/position/risk management
- Equity curve tracking throughout the backtest
- Comprehensive metrics calculation and result generation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cryptrink.backtest.executor import BacktestExecutor
from cryptrink.backtest.metrics import BacktestMetricsCalculator
from cryptrink.backtest.models import ConstantSlippageModel, PercentageFeeModel
from cryptrink.core.logging import get_logger
from cryptrink.execution.engine import TradingEngine
from cryptrink.strategies.base import StrategyContext

if TYPE_CHECKING:
    from cryptrink.backtest.result import BacktestResult
    from cryptrink.data.feeds import HistoricalDataFeed  # type: ignore[import-untyped]
    from cryptrink.data.models import OHLCV  # type: ignore[import-untyped]
    from cryptrink.execution.risk import RiskSettings  # type: ignore[import-untyped]
    from cryptrink.strategies.base import BaseStrategy

logger = get_logger(__name__)


class BacktestEngine:
    """Main backtesting orchestration engine with event-driven replay.

    This engine coordinates all aspects of backtesting:
    1. Loads historical OHLCV data with lookback for indicators
    2. Replays data candle-by-candle in event-driven manner
    3. Builds rolling StrategyContext for each candle
    4. Generates signals via strategy and executes via TradingEngine
    5. Tracks equity curve and calculates comprehensive metrics

    The engine uses BacktestExecutor for realistic order simulation
    with slippage and fees, and integrates with the full TradingEngine
    stack (OrderManager, PositionTracker, RiskValidator).
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        data_feed: HistoricalDataFeed,
        initial_balance: Decimal = Decimal("10000"),
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        slippage_bps: Decimal = Decimal("0.0005"),  # 5 bps default
        fee_pct: Decimal = Decimal("0.0009"),  # 0.09% default (RevolutX taker fee)
        risk_settings: RiskSettings | None = None,
    ) -> None:
        """Initialize backtest engine.

        Args:
            strategy: Trading strategy to backtest.
            data_feed: Historical data feed for loading OHLCV data.
            initial_balance: Starting balance for backtest (default: $10,000).
            session_factory: Database session factory (optional, creates in-memory if None).
            slippage_bps: Slippage in basis points (default: 5 bps).
            fee_pct: Trading fee percentage (default: 0.09%).
            risk_settings: Risk management settings (optional).
        """
        self._strategy = strategy
        self._data_feed = data_feed
        self._initial_balance = initial_balance

        # Create slippage and fee models
        self._slippage_model = ConstantSlippageModel(slippage_bps=slippage_bps)
        self._fee_model = PercentageFeeModel(fee_pct=fee_pct)

        # Create backtest executor
        self._executor = BacktestExecutor(
            initial_balance=initial_balance,
            slippage_model=self._slippage_model,
            fee_model=self._fee_model,
        )

        # Create session factory if not provided (in-memory for backtest)
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

        # Create TradingEngine with backtest executor
        self._engine = TradingEngine(
            strategy=strategy,
            executor=self._executor,
            session_factory=session_factory,
            initial_balance=initial_balance,
            risk_settings=risk_settings,
        )

        # Backtest-specific tracking
        self._metrics_calculator = BacktestMetricsCalculator()
        self._equity_curve: list[tuple[datetime, Decimal]] = []

        logger.info(
            "backtest_engine_initialized",
            strategy=strategy.__class__.__name__,
            initial_balance=float(initial_balance),
            slippage_bps=float(slippage_bps),
            fee_pct=float(fee_pct),
        )

    async def run(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1h",
        lookback_periods: int = 200,
    ) -> BacktestResult:
        """Run backtest on historical data.

        This method performs event-driven backtesting by:
        1. Loading historical OHLCV data (with lookback for indicators)
        2. Iterating candle-by-candle in chronological order
        3. Building rolling StrategyContext for each candle
        4. Generating signals and executing via TradingEngine
        5. Tracking equity curve throughout
        6. Calculating comprehensive performance metrics

        Args:
            symbol: Trading symbol (e.g., "BTC-USD").
            start_time: Backtest start time.
            end_time: Backtest end time.
            timeframe: OHLCV timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d).
            lookback_periods: Number of historical candles for indicator warmup.

        Returns:
            BacktestResult with comprehensive metrics and trade history.

        Raises:
            ValueError: If no historical data found or insufficient data.
        """
        logger.info(
            "backtest_starting",
            symbol=symbol,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            timeframe=timeframe,
            lookback_periods=lookback_periods,
        )

        # 1. Initialize database if using in-memory
        if self._owns_session_factory:
            await self._initialize_database()

        # 2. Calculate lookback start time
        lookback_start = self._calculate_lookback_start(start_time, timeframe, lookback_periods)

        # 3. Load historical OHLCV data
        ohlcv_data = await self._data_feed.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            start_time=lookback_start,
            end_time=end_time,
        )

        if not ohlcv_data:
            msg = f"No historical data found for {symbol} {timeframe}"
            raise ValueError(msg)

        logger.info(
            "historical_data_loaded",
            symbol=symbol,
            candles=len(ohlcv_data),
            first_candle=ohlcv_data[0].timestamp.isoformat(),
            last_candle=ohlcv_data[-1].timestamp.isoformat(),
        )

        # 4. Convert to DataFrame once; per-candle context slices a rolling
        #    window from this single frame.
        df = self._build_dataframe(ohlcv_data)

        # 5. Record initial equity
        self._equity_curve.append((start_time, self._initial_balance))

        # 6. Event-by-event replay: for each in-window candle, build a
        #    StrategyContext over the rolling history, ask the strategy for a
        #    signal, and route it through TradingEngine for risk validation
        #    and execution.
        for current_index, candle in enumerate(ohlcv_data):
            # Skip lookback period (indicators need historical data)
            if candle.timestamp < start_time:
                continue

            context = self._build_strategy_context(
                symbol=symbol,
                current_index=current_index,
                df=df,
            )
            signal = self._strategy.generate_signal(context)

            await self._engine.process_signal(
                symbol=symbol,
                current_price=candle.close,
                timestamp=candle.timestamp,
                signal=signal,
            )

            # Record equity at this point
            current_equity = self._executor.balance
            self._equity_curve.append((candle.timestamp, current_equity))

        # 7. Close any open positions at end
        await self._close_all_positions(symbol, ohlcv_data[-1].close, end_time)

        # 8. Calculate comprehensive metrics
        result = await self._calculate_results(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )

        logger.info(
            "backtest_completed",
            symbol=symbol,
            final_balance=str(result.metrics.ending_equity),
            total_return_pct=f"{float(result.metrics.total_return_pct) * 100:.2f}%",
            sharpe_ratio=str(result.metrics.sharpe_ratio),
            total_trades=result.metrics.total_trades,
        )

        return result

    async def _initialize_database(self) -> None:
        """Initialize in-memory database schema.

        Only creates execution tables (Order, Position) as backtest data
        is provided via the data_feed parameter, not stored in database.
        """
        from cryptrink.execution.models import Position

        # Create engine from session factory
        engine = self._session_factory.kw["bind"]

        # Create execution tables only (Order, Position)
        # Note: Position.metadata includes all execution models
        async with engine.begin() as conn:
            await conn.run_sync(Position.metadata.create_all)

        logger.debug("in_memory_database_initialized")

    def _calculate_lookback_start(
        self, start_time: datetime, timeframe: str, lookback_periods: int
    ) -> datetime:
        """Calculate start time including lookback period for indicators.

        Args:
            start_time: Desired backtest start time.
            timeframe: OHLCV timeframe.
            lookback_periods: Number of periods to look back.

        Returns:
            Adjusted start time including lookback.
        """
        # Parse timeframe to timedelta
        timeframe_map = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "1d": timedelta(days=1),
        }

        if timeframe not in timeframe_map:
            msg = f"Unsupported timeframe: {timeframe}"
            raise ValueError(msg)

        delta = timeframe_map[timeframe]
        lookback_start = start_time - (delta * lookback_periods)

        logger.debug(
            "lookback_calculated",
            start_time=start_time.isoformat(),
            lookback_start=lookback_start.isoformat(),
            lookback_periods=lookback_periods,
        )

        return lookback_start

    def _build_dataframe(self, ohlcv_data: list[OHLCV]) -> pd.DataFrame:
        """Convert OHLCV data to pandas DataFrame for strategy.

        Args:
            ohlcv_data: List of OHLCV candles.

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume.
        """
        data = {
            "timestamp": [candle.timestamp for candle in ohlcv_data],
            "open": [float(candle.open) for candle in ohlcv_data],
            "high": [float(candle.high) for candle in ohlcv_data],
            "low": [float(candle.low) for candle in ohlcv_data],
            "close": [float(candle.close) for candle in ohlcv_data],
            "volume": [float(candle.volume) for candle in ohlcv_data],
        }

        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)

        return df

    def _build_strategy_context(
        self,
        symbol: str,
        current_index: int,
        df: pd.DataFrame,
    ) -> StrategyContext:
        """Build StrategyContext for strategy signal generation.

        Includes all historical data up to current_index (rolling window).

        Args:
            symbol: Trading symbol.
            current_index: Current candle index in DataFrame.
            df: Full OHLCV DataFrame.

        Returns:
            StrategyContext with rolling historical data.
        """
        from cryptrink.exchange.base import OrderSide

        # Slice DataFrame up to current candle (inclusive)
        historical_df = df.iloc[: current_index + 1].copy()

        # Get current price from the last candle
        current_price = Decimal(str(historical_df.iloc[-1]["close"]))

        # Get current position from executor
        position = self._executor.get_position(symbol)
        position_size = Decimal("0")
        position_side: OrderSide | None = None

        if position is not None:
            # Position is dict[str, object], need to extract values safely
            position_size = Decimal(str(position.get("quantity", "0")))
            side_str = position.get("side")
            if side_str == "long":
                position_side = OrderSide.BUY
            elif side_str == "short":
                position_side = OrderSide.SELL

        return StrategyContext(
            symbol=symbol,
            current_price=current_price,
            timestamp=historical_df.index[-1],
            ohlcv=historical_df,
            position_size=position_size,
            position_side=position_side,
        )

    async def _close_all_positions(
        self, symbol: str, current_price: Decimal, timestamp: datetime
    ) -> None:
        """Close any open positions at end of backtest.

        Forces an explicit EXIT signal directly through the BacktestExecutor.
        We bypass TradingEngine here because its PositionTracker is not yet
        synced with executor-internal state (BacktestExecutor maintains its
        own positions dict), and risk validation does not apply to a forced
        end-of-backtest unwind.

        Args:
            symbol: Trading symbol.
            current_price: Current market price.
            timestamp: Current timestamp.
        """
        from cryptrink.execution.base import ExecutionContext
        from cryptrink.strategies.base import Signal, SignalStrength, SignalType

        position = self._executor.get_position(symbol)
        if position is None:
            return

        side_str = position.get("side")
        exit_signal_type = (
            SignalType.EXIT_SHORT if side_str == "short" else SignalType.EXIT_LONG
        )
        quantity_str = str(position.get("quantity", "0"))
        position_size = Decimal(quantity_str)

        logger.info(
            "closing_position_at_backtest_end",
            symbol=symbol,
            quantity=quantity_str,
            price=str(current_price),
            exit_signal=exit_signal_type.value,
        )

        exit_signal = Signal(
            signal_type=exit_signal_type,
            symbol=symbol,
            timestamp=timestamp,
            price=current_price,
            strength=SignalStrength.STRONG,
        )
        exit_context = ExecutionContext(
            symbol=symbol,
            current_price=current_price,
            timestamp=timestamp,
            account_balance=self._executor.balance,
            has_position=True,
            position_size=position_size,
        )

        await self._executor.execute_signal(exit_signal, exit_context)

    async def _calculate_results(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> BacktestResult:
        """Calculate final backtest results with comprehensive metrics.

        Args:
            symbol: Trading symbol.
            timeframe: OHLCV timeframe.
            start_time: Backtest start time.
            end_time: Backtest end time.

        Returns:
            BacktestResult with metrics, equity curve, and trade history.
        """
        from cryptrink.backtest.result import BacktestResult

        # Get all closed positions from TradingEngine
        async with self._session_factory() as session:
            # Query closed positions
            from sqlalchemy import select

            from cryptrink.execution.models import Order, Position

            positions_result = await session.execute(
                select(Position).where(Position.status == "closed")
            )
            positions = list(positions_result.scalars().all())

            # Query all orders
            orders_result = await session.execute(select(Order))
            orders = list(orders_result.scalars().all())

        # Calculate metrics
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

        # Calculate drawdown curve
        drawdown_curve = self._calculate_drawdown_curve(self._equity_curve)

        return BacktestResult(
            strategy_name=self._strategy.__class__.__name__,
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            initial_balance=self._initial_balance,
            metrics=metrics,
            equity_curve=self._equity_curve,
            trades=positions,
            orders=orders,
            drawdown_curve=drawdown_curve,
        )

    def _calculate_drawdown_curve(
        self, equity_curve: list[tuple[datetime, Decimal]]
    ) -> list[tuple[datetime, Decimal]]:
        """Calculate drawdown at each point in time.

        Args:
            equity_curve: List of (timestamp, equity) tuples.

        Returns:
            List of (timestamp, drawdown) tuples where drawdown is percentage.
        """
        if len(equity_curve) < 2:
            return []

        drawdown_curve: list[tuple[datetime, Decimal]] = []
        peak_equity = equity_curve[0][1]

        for timestamp, equity in equity_curve:
            # Update peak
            if equity > peak_equity:
                peak_equity = equity

            # Calculate drawdown percentage
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else Decimal("0")
            drawdown_curve.append((timestamp, drawdown))

        return drawdown_curve
