"""Trading engine for orchestrating strategy execution and order management.

This module provides the TradingEngine class that coordinates between strategies,
executors, order management, and position tracking to execute a complete trading system.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cryptrink.core.config import RiskSettings
from cryptrink.core.logging import get_logger
from cryptrink.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
)
from cryptrink.execution.models import EngineState
from cryptrink.execution.order_manager import OrderManager
from cryptrink.execution.position_tracker import PositionTracker
from cryptrink.execution.repository import EngineStateRepository, OrderRepository
from cryptrink.risk.metrics import RiskMetricsTracker
from cryptrink.risk.validator import RiskValidator
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
        risk_settings: RiskSettings | None = None,
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
            risk_settings: Optional risk management settings (uses defaults if not provided).
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

        # Initialize risk management components
        self._risk_settings = risk_settings or RiskSettings()
        self._risk_validator = RiskValidator(self._risk_settings)
        self._risk_metrics = RiskMetricsTracker(initial_balance)

        # Engine state
        self._is_running = False
        self._signal_count = 0
        self._execution_count = 0
        self._circuit_breaker_active = False

        logger.info(
            "trading_engine_initialized",
            engine_id=self._engine_id,
            strategy=strategy.__class__.__name__,
            executor_mode=executor.mode.value,
            initial_balance=float(initial_balance),
            max_position_size=float(max_position_size),
            max_open_positions=max_open_positions,
            risk_management_enabled=True,
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
        if not await self._validate_signal(signal, context):
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

    async def _validate_signal(self, signal: Signal, context: ExecutionContext) -> bool:
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

        # Check circuit breaker first
        if self._circuit_breaker_active and signal.signal_type in [
            SignalType.ENTRY_LONG,
            SignalType.ENTRY_SHORT,
        ]:
            logger.warning(
                "signal_rejected_circuit_breaker_active",
                symbol=signal.symbol,
                circuit_breaker_reason=self._risk_metrics.metrics.circuit_breaker_reason,
            )
            return False

        # For exit signals, verify we have a position (but always allow exits)
        if (signal.signal_type in [SignalType.EXIT_LONG, SignalType.EXIT_SHORT]) and (
            not context.has_position
        ):
            logger.debug("exit_signal_rejected_no_position", symbol=signal.symbol)
            return False

        # For entry signals, use RiskValidator
        if signal.signal_type in [SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT]:
            # Determine order side
            from cryptrink.execution.base import calculate_quantity, determine_order_side

            order_side = determine_order_side(signal.signal_type)

            # Calculate quantity for this order
            quantity = calculate_quantity(
                context=context,
                order_side=order_side,
                signal=signal,
                position_sizer=None,  # Using simple allocation for now
            )

            # Get open positions count
            all_open_positions = await self._position_tracker.get_open_positions()
            open_positions_count = len(all_open_positions)

            # Validate with RiskValidator
            validation_result = self._risk_validator.validate_order(
                signal=signal,
                quantity=quantity,
                context=context,
                order_side=order_side,
                metrics=self._risk_metrics.metrics,
                open_positions_count=open_positions_count,
            )

            if not validation_result.valid:
                logger.warning(
                    "signal_rejected_by_risk_validator",
                    symbol=signal.symbol,
                    reason=validation_result.reason,
                    circuit_breaker=validation_result.circuit_breaker_triggered,
                )

                # Activate circuit breaker if triggered
                if validation_result.circuit_breaker_triggered:
                    self._circuit_breaker_active = True
                    if validation_result.circuit_breaker_reason:
                        self._risk_metrics.activate_circuit_breaker(
                            validation_result.circuit_breaker_reason
                        )

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

    async def resume_trading(self) -> None:
        """Manually resume trading after circuit breaker activation.

        This should only be called after reviewing the reason for circuit breaker
        activation and confirming it's safe to resume trading.
        """
        if not self._circuit_breaker_active:
            logger.warning("circuit_breaker_not_active_no_action_needed")
            return

        previous_reason = self._risk_metrics.metrics.circuit_breaker_reason

        self._circuit_breaker_active = False
        self._risk_metrics.deactivate_circuit_breaker()

        await self.save_state()
        logger.warning(
            "trading_resumed_circuit_breaker_cleared",
            previous_reason=previous_reason,
        )

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
        risk metrics, and configuration for recovery purposes.
        """
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        metrics = self._risk_metrics.metrics

        # Convert circuit breaker timestamp if present
        circuit_breaker_triggered_at = None
        if metrics.circuit_breaker_triggered_at:
            circuit_breaker_triggered_at = int(
                metrics.circuit_breaker_triggered_at.timestamp() * 1000
            )

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
            # Risk Metrics - P&L Tracking
            daily_realized_pnl=str(metrics.daily_realized_pnl),
            daily_unrealized_pnl=str(metrics.daily_unrealized_pnl),
            total_realized_pnl=str(metrics.total_realized_pnl),
            # Risk Metrics - Drawdown Tracking
            peak_equity=str(metrics.peak_equity),
            current_drawdown=str(metrics.current_drawdown),
            max_drawdown=str(metrics.max_drawdown),
            # Risk Metrics - Win Rate Tracking
            win_count=metrics.win_count,
            loss_count=metrics.loss_count,
            total_trades=metrics.total_trades,
            total_win_amount=str(metrics.total_win_amount),
            total_loss_amount=str(metrics.total_loss_amount),
            # Risk Metrics - Circuit Breaker State
            circuit_breaker_active=metrics.circuit_breaker_active,
            circuit_breaker_reason=metrics.circuit_breaker_reason,
            circuit_breaker_triggered_at=circuit_breaker_triggered_at,
            # Risk Metrics - Timestamp Tracking
            risk_metrics_last_reset_at=int(metrics.last_reset_at.timestamp() * 1000),
            risk_metrics_last_updated_at=int(metrics.last_updated_at.timestamp() * 1000),
            # Standard timestamps
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

        # Restore risk metrics
        from cryptrink.risk.metrics import RiskMetrics

        restored_metrics = RiskMetrics(
            daily_realized_pnl=engine_state.daily_realized_pnl_decimal,
            daily_unrealized_pnl=engine_state.daily_unrealized_pnl_decimal,
            total_realized_pnl=engine_state.total_realized_pnl_decimal,
            peak_equity=engine_state.peak_equity_decimal,
            current_drawdown=engine_state.current_drawdown_decimal,
            max_drawdown=engine_state.max_drawdown_decimal,
            win_count=engine_state.win_count,
            loss_count=engine_state.loss_count,
            total_trades=engine_state.total_trades,
            total_win_amount=engine_state.total_win_amount_decimal,
            total_loss_amount=engine_state.total_loss_amount_decimal,
            circuit_breaker_active=engine_state.circuit_breaker_active,
            circuit_breaker_reason=engine_state.circuit_breaker_reason,
            circuit_breaker_triggered_at=engine_state.circuit_breaker_triggered_datetime,
            last_reset_at=engine_state.risk_metrics_last_reset_datetime,
            last_updated_at=engine_state.risk_metrics_last_updated_datetime,
        )

        # Replace the tracker's metrics with restored state
        engine._risk_metrics._metrics = restored_metrics
        engine._circuit_breaker_active = restored_metrics.circuit_breaker_active

        logger.info(
            "engine_state_loaded",
            engine_id=engine_id,
            is_running=engine_state.is_running,
            signal_count=engine_state.signal_count,
            circuit_breaker_active=restored_metrics.circuit_breaker_active,
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
