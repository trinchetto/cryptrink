"""Trading engine for orchestrating strategy execution and order management.

This module provides the TradingEngine class that coordinates between strategies,
executors, order management, and position tracking to execute a complete trading system.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cryptrink.core.logging import get_logger
from cryptrink.execution.base import BaseExecutor, ExecutionContext, ExecutionMode, ExecutionResult
from cryptrink.execution.models import EngineState
from cryptrink.execution.order_manager import OrderManager
from cryptrink.execution.position_tracker import PositionTracker
from cryptrink.execution.repository import EngineStateRepository, OrderRepository
from cryptrink.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType

logger = get_logger(__name__)


class TradingEngine:
    """Main trading engine orchestrator.

    Coordinates strategy execution, order placement, and position tracking.
    Manages the trading loop and ensures proper flow between all components.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        executor: BaseExecutor,
        session_factory: async_sessionmaker[AsyncSession],
        engine_id: str | None = None,
        initial_balance: Decimal = Decimal("10000"),
        max_position_size: Decimal = Decimal("0.1"),  # 10% of balance per position
        max_open_positions: int = 5,
    ) -> None:
        """Initialize the trading engine.

        Args:
            strategy: Trading strategy to use for signal generation.
            executor: Executor for placing orders (suggest, paper, or live).
            session_factory: SQLAlchemy async session factory for persistence.
            engine_id: Optional unique engine ID for state persistence.
            initial_balance: Initial account balance.
            max_position_size: Maximum position size as fraction of balance (default 10%).
            max_open_positions: Maximum number of concurrent open positions.
        """
        self._strategy = strategy
        self._executor = executor
        self._session_factory = session_factory
        self._initial_balance = initial_balance
        self._current_balance = initial_balance
        self._max_position_size = max_position_size
        self._max_open_positions = max_open_positions

        # Engine identification
        import uuid

        self._engine_id = engine_id or str(uuid.uuid4())

        # Initialize order manager, position tracker, and repositories
        self._order_manager = OrderManager(session_factory)
        self._position_tracker = PositionTracker(session_factory)
        self._order_repo = OrderRepository(session_factory)
        self._state_repo = EngineStateRepository(session_factory)

        # Engine state
        self._is_running = False
        self._signal_count = 0
        self._execution_count = 0

        logger.info(
            "trading_engine_initialized",
            engine_id=self._engine_id,
            strategy=strategy.__class__.__name__,
            executor_mode=executor.mode.value,
            initial_balance=float(initial_balance),
            max_position_size=float(max_position_size),
            max_open_positions=max_open_positions,
        )

    async def process_signal(
        self,
        symbol: str,
        current_price: Decimal,
        timestamp: datetime | None = None,
    ) -> ExecutionResult:
        """Process market data and execute trading logic.

        This is the main entry point for the trading engine. It:
        1. Generates signal from strategy
        2. Validates signal against risk management rules
        3. Executes signal via executor
        4. Records order and position updates

        Args:
            symbol: Trading symbol to process.
            current_price: Current market price.
            timestamp: Optional timestamp (defaults to now).

        Returns:
            ExecutionResult with outcome of the signal processing.
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        self._signal_count += 1

        # Check if we have an open position for this symbol
        open_positions = await self._position_tracker.get_open_positions(symbol=symbol)
        has_position = len(open_positions) > 0
        position_size = sum(
            (p.quantity_decimal for p in open_positions),
            Decimal("0"),
        )

        # Update unrealized P&L for open positions
        for position in open_positions:
            await self._position_tracker.update_unrealized_pnl(
                position_id=position.position_id, current_price=current_price
            )

        # Create execution context
        context = ExecutionContext(
            symbol=symbol,
            current_price=current_price,
            timestamp=timestamp,
            account_balance=self._current_balance,
            has_position=has_position,
            position_size=position_size,
        )

        # Generate signal from strategy
        # Note: Strategy needs market data - this is simplified, real implementation
        # would pass historical data to strategy.generate_signal()
        logger.debug(
            "generating_signal",
            symbol=symbol,
            price=float(current_price),
            has_position=has_position,
        )

        # For now, we'll assume the strategy has access to the data it needs
        # In a real implementation, you'd call strategy.generate_signal(market_data)
        # This is a placeholder - the actual integration would depend on how
        # market data is fed to the engine
        signal = Signal(
            signal_type=SignalType.HOLD,
            symbol=symbol,
            timestamp=timestamp,
            price=current_price,
            strength=SignalStrength.MODERATE,
        )

        # Validate signal against risk management rules
        if not self._validate_signal(signal, context):
            logger.info(
                "signal_rejected_by_risk_management",
                symbol=symbol,
                signal_type=signal.signal_type.value,
            )
            return ExecutionResult(
                success=False,
                message="Signal rejected by risk management",
                order_id=None,
            )

        # Execute signal
        logger.info(
            "executing_signal",
            symbol=symbol,
            signal_type=signal.signal_type.value,
            signal_strength=signal.strength.value,
        )

        result = await self._executor.execute_signal(signal, context)
        self._execution_count += 1

        # If execution was successful and we're not in suggest mode, record the order/position
        if result.success and self._executor.mode != ExecutionMode.SUGGEST:
            await self._record_execution(signal, result, context)

        return result

    def _validate_signal(self, signal: Signal, context: ExecutionContext) -> bool:
        """Validate signal against risk management rules.

        Args:
            signal: Signal to validate.
            context: Current execution context.

        Returns:
            True if signal passes validation, False otherwise.
        """
        # HOLD signals always pass
        if signal.signal_type == SignalType.HOLD:
            return True

        # For entry signals, check position limits
        if signal.signal_type in [SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT]:
            # Check max open positions
            # Note: This is a simplified check - in production you'd query the position tracker
            if context.has_position:
                logger.debug("entry_signal_rejected_already_has_position", symbol=signal.symbol)
                return False

            # Check if we have enough balance
            if context.account_balance <= 0:
                logger.debug("entry_signal_rejected_insufficient_balance", symbol=signal.symbol)
                return False

        # For exit signals, verify we have a position
        if (signal.signal_type in [SignalType.EXIT_LONG, SignalType.EXIT_SHORT]) and (
            not context.has_position
        ):
            logger.debug("exit_signal_rejected_no_position", symbol=signal.symbol)
            return False

        return True

    async def _record_execution(
        self, signal: Signal, result: ExecutionResult, context: ExecutionContext
    ) -> None:
        """Record execution results in order manager and position tracker.

        Args:
            signal: Signal that was executed.
            result: Execution result.
            context: Execution context.
        """
        # For paper and live modes, the executor already handles order/position tracking
        # This method is a hook for additional bookkeeping if needed
        logger.debug(
            "execution_recorded",
            order_id=result.order_id,
            signal_type=signal.signal_type.value,
            success=result.success,
        )

    async def get_performance_summary(self) -> dict[str, object]:
        """Get engine performance summary.

        Returns:
            Dictionary with performance metrics.
        """
        # Get P&L from position tracker
        total_pnl = await self._position_tracker.get_total_pnl()

        # Get open positions
        open_positions = await self._position_tracker.get_open_positions()

        # Get recent orders from repository
        recent_orders = await self._order_repo.get_recent_orders(limit=10)

        return {
            "initial_balance": float(self._initial_balance),
            "current_balance": float(self._current_balance),
            "total_pnl": float(total_pnl["total_pnl"]),
            "realized_pnl": float(total_pnl["realized_pnl"]),
            "unrealized_pnl": float(total_pnl["unrealized_pnl"]),
            "total_fees": float(total_pnl["total_fees"]),
            "open_positions_count": len(open_positions),
            "signal_count": self._signal_count,
            "execution_count": self._execution_count,
            "recent_orders_count": len(recent_orders),
        }

    async def start(self) -> None:
        """Start the trading engine.

        Marks the engine as running and ready to process signals.
        """
        if self._is_running:
            logger.warning("trading_engine_already_running")
            return

        self._is_running = True
        await self.save_state()
        logger.info("trading_engine_started")

    async def stop(self) -> None:
        """Stop the trading engine.

        Marks the engine as stopped. Does not close positions.
        """
        if not self._is_running:
            logger.warning("trading_engine_not_running")
            return

        self._is_running = False
        await self.save_state()
        logger.info("trading_engine_stopped")

    async def reset(self, initial_balance: Decimal | None = None) -> None:
        """Reset the trading engine state.

        Args:
            initial_balance: Optional new initial balance.
        """
        self._is_running = False
        self._signal_count = 0
        self._execution_count = 0

        if initial_balance is not None:
            self._initial_balance = initial_balance
            self._current_balance = initial_balance

        # Reset strategy state
        self._strategy.reset()

        await self.save_state()
        logger.info("trading_engine_reset", initial_balance=float(self._initial_balance))

    async def save_state(self) -> None:
        """Save the current engine state to the database.

        Persists all engine state including running status, balances, counters,
        and configuration for recovery purposes.
        """
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        engine_state = EngineState(
            engine_id=self._engine_id,
            strategy_name=self._strategy.__class__.__name__,
            executor_mode=self._executor.mode.value,
            is_running=self._is_running,
            initial_balance=str(self._initial_balance),
            current_balance=str(self._current_balance),
            max_position_size=str(self._max_position_size),
            max_open_positions=self._max_open_positions,
            signal_count=self._signal_count,
            execution_count=self._execution_count,
            created_at=now_ms,
            updated_at=now_ms,
            last_signal_at=None,
        )

        await self._state_repo.save_state(engine_state)
        logger.debug("engine_state_saved", engine_id=self._engine_id)

    @classmethod
    async def load_state(
        cls,
        engine_id: str,
        strategy: BaseStrategy,
        executor: BaseExecutor,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> "TradingEngine | None":
        """Load and restore engine state from the database.

        Args:
            engine_id: The engine ID to load state for.
            strategy: Trading strategy to use.
            executor: Executor to use.
            session_factory: SQLAlchemy async session factory.

        Returns:
            TradingEngine instance with restored state, or None if not found.
        """
        state_repo = EngineStateRepository(session_factory)
        engine_state = await state_repo.load_state(engine_id)

        if engine_state is None:
            logger.warning("engine_state_not_found", engine_id=engine_id)
            return None

        # Create engine with restored state
        engine = cls(
            strategy=strategy,
            executor=executor,
            session_factory=session_factory,
            engine_id=engine_id,
            initial_balance=engine_state.initial_balance_decimal,
            max_position_size=engine_state.max_position_size_decimal,
            max_open_positions=engine_state.max_open_positions,
        )

        # Restore runtime state
        engine._current_balance = engine_state.current_balance_decimal
        engine._is_running = engine_state.is_running
        engine._signal_count = engine_state.signal_count
        engine._execution_count = engine_state.execution_count

        logger.info(
            "engine_state_loaded",
            engine_id=engine_id,
            is_running=engine_state.is_running,
            signal_count=engine_state.signal_count,
        )

        return engine

    @property
    def engine_id(self) -> str:
        """Get the engine ID."""
        return self._engine_id

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._is_running

    @property
    def strategy(self) -> BaseStrategy:
        """Get the trading strategy."""
        return self._strategy

    @property
    def executor(self) -> BaseExecutor:
        """Get the executor."""
        return self._executor

    @property
    def order_manager(self) -> OrderManager:
        """Get the order manager."""
        return self._order_manager

    @property
    def position_tracker(self) -> PositionTracker:
        """Get the position tracker."""
        return self._position_tracker

    def __repr__(self) -> str:
        """String representation of TradingEngine."""
        return (
            f"TradingEngine(engine_id={self._engine_id!r}, "
            f"strategy={self._strategy.__class__.__name__}, "
            f"mode={self._executor.mode.value}, "
            f"balance={self._current_balance}, "
            f"running={self._is_running})"
        )
