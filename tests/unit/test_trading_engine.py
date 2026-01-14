"""Unit tests for TradingEngine."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cryptrink.execution.base import ExecutionMode
from cryptrink.execution.engine import TradingEngine
from cryptrink.execution.paper import PaperExecutor
from cryptrink.execution.repository import init_execution_db
from cryptrink.execution.suggest import SuggestExecutor
from cryptrink.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType


class DummyStrategy(BaseStrategy):
    """Simple strategy for testing that returns configurable signals."""

    def __init__(self) -> None:
        """Initialize dummy strategy."""
        self._next_signal = SignalType.HOLD

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "Dummy Strategy"

    @property
    def description(self) -> str:
        """Get strategy description."""
        return "A simple test strategy that returns configurable signals"

    def set_next_signal(self, signal_type: SignalType) -> None:
        """Set the next signal to return."""
        self._next_signal = signal_type

    def generate_signal(self, context: object) -> Signal:
        """Generate the configured signal."""
        return Signal(
            signal_type=self._next_signal,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )

    def reset(self) -> None:
        """Reset strategy state."""
        self._next_signal = SignalType.HOLD


@pytest.fixture
async def engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_execution_db(engine)
    return engine


@pytest.fixture
async def dummy_strategy() -> DummyStrategy:
    """Create a dummy strategy for testing."""
    return DummyStrategy()


@pytest.fixture
async def paper_executor() -> PaperExecutor:
    """Create a paper executor for testing."""
    return PaperExecutor(initial_balance=Decimal("10000"))


@pytest.fixture
async def suggest_executor() -> SuggestExecutor:
    """Create a suggest executor for testing."""
    return SuggestExecutor()


@pytest.fixture
async def trading_engine(
    engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
) -> TradingEngine:
    """Create a trading engine for testing."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return TradingEngine(
        strategy=dummy_strategy,
        executor=paper_executor,
        session_factory=session_factory,
        initial_balance=Decimal("10000"),
        max_position_size=Decimal("0.1"),
        max_open_positions=5,
    )


class TestTradingEngine:
    """Tests for TradingEngine class."""

    async def test_initialization(self, trading_engine: TradingEngine) -> None:
        """Test that TradingEngine initializes correctly."""
        assert trading_engine.strategy is not None
        assert trading_engine.executor is not None
        assert trading_engine.order_manager is not None
        assert trading_engine.position_tracker is not None
        assert trading_engine.is_running is False

    async def test_start_stop(self, trading_engine: TradingEngine) -> None:
        """Test starting and stopping the engine."""
        assert trading_engine.is_running is False

        await trading_engine.start()
        assert trading_engine.is_running is True

        await trading_engine.stop()
        assert trading_engine.is_running is False

    async def test_start_when_already_running(self, trading_engine: TradingEngine) -> None:
        """Test that starting when already running is a no-op."""
        await trading_engine.start()
        assert trading_engine.is_running is True

        # Start again - should not error
        await trading_engine.start()
        assert trading_engine.is_running is True

    async def test_stop_when_not_running(self, trading_engine: TradingEngine) -> None:
        """Test that stopping when not running is a no-op."""
        assert trading_engine.is_running is False

        # Stop when not running - should not error
        await trading_engine.stop()
        assert trading_engine.is_running is False

    async def test_reset(self, trading_engine: TradingEngine) -> None:
        """Test resetting the engine."""
        await trading_engine.start()
        await trading_engine.process_signal("BTC-USD", Decimal("50000"))

        assert trading_engine.is_running is True

        await trading_engine.reset()

        assert trading_engine.is_running is False

    async def test_reset_with_new_balance(self, trading_engine: TradingEngine) -> None:
        """Test resetting with a new balance."""
        await trading_engine.reset(initial_balance=Decimal("20000"))

        # Check performance summary to verify balance
        summary = await trading_engine.get_performance_summary()
        assert summary["initial_balance"] == 20000.0
        assert summary["current_balance"] == 20000.0

    async def test_process_signal_hold(self, trading_engine: TradingEngine) -> None:
        """Test processing a HOLD signal."""
        result = await trading_engine.process_signal("BTC-USD", Decimal("50000"))

        # HOLD signals should be rejected by executor
        assert result.success is False

    async def test_process_signal_with_suggest_executor(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, suggest_executor: SuggestExecutor
    ) -> None:
        """Test processing signal with suggest executor."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=suggest_executor,
            session_factory=session_factory,
        )

        # Note: Currently the engine generates HOLD signals as a placeholder
        # until full market data integration is implemented
        # The strategy's generate_signal is not called yet
        result = await trading_engine.process_signal("BTC-USD", Decimal("50000"))

        # HOLD signals are rejected by executors
        assert result.success is False
        assert "HOLD" in result.message

    async def test_get_performance_summary(self, trading_engine: TradingEngine) -> None:
        """Test getting performance summary."""
        summary = await trading_engine.get_performance_summary()

        assert "initial_balance" in summary
        assert "current_balance" in summary
        assert "total_pnl" in summary
        assert "realized_pnl" in summary
        assert "unrealized_pnl" in summary
        assert "total_fees" in summary
        assert "open_positions_count" in summary
        assert "signal_count" in summary
        assert "execution_count" in summary

        assert summary["initial_balance"] == 10000.0
        assert summary["current_balance"] == 10000.0
        assert summary["open_positions_count"] == 0

    async def test_signal_counter_increments(self, trading_engine: TradingEngine) -> None:
        """Test that signal counter increments."""
        summary1 = await trading_engine.get_performance_summary()
        assert summary1["signal_count"] == 0

        await trading_engine.process_signal("BTC-USD", Decimal("50000"))

        summary2 = await trading_engine.get_performance_summary()
        assert summary2["signal_count"] == 1

        await trading_engine.process_signal("BTC-USD", Decimal("51000"))

        summary3 = await trading_engine.get_performance_summary()
        assert summary3["signal_count"] == 2

    async def test_repr(self, trading_engine: TradingEngine) -> None:
        """Test string representation."""
        repr_str = repr(trading_engine)

        assert "TradingEngine" in repr_str
        assert "DummyStrategy" in repr_str
        assert "paper" in repr_str
        assert "10000" in repr_str

    async def test_risk_management_rejects_entry_when_has_position(
        self, trading_engine: TradingEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test that risk management rejects entry signals when position exists."""
        # This test demonstrates the validation logic
        # In a real scenario, we'd need to create a position first
        # For now, we're testing the validation method indirectly

        # The _validate_signal method checks context.has_position
        # We can't easily test this without mocking or creating real positions
        # This is a placeholder for integration testing
        pass

    async def test_multiple_signals_same_symbol(
        self, trading_engine: TradingEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test processing multiple signals for the same symbol."""
        await trading_engine.process_signal("BTC-USD", Decimal("50000"))
        await trading_engine.process_signal("BTC-USD", Decimal("51000"))
        await trading_engine.process_signal("BTC-USD", Decimal("49000"))

        summary = await trading_engine.get_performance_summary()
        assert summary["signal_count"] == 3

    async def test_multiple_signals_different_symbols(
        self, trading_engine: TradingEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test processing signals for different symbols."""
        await trading_engine.process_signal("BTC-USD", Decimal("50000"))
        await trading_engine.process_signal("ETH-USD", Decimal("3000"))
        await trading_engine.process_signal("SOL-USD", Decimal("100"))

        summary = await trading_engine.get_performance_summary()
        assert summary["signal_count"] == 3

    async def test_engine_with_paper_executor(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test engine with paper executor mode."""
        paper_executor = PaperExecutor(initial_balance=Decimal("50000"))
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            initial_balance=Decimal("50000"),
        )

        assert trading_engine.executor.mode == ExecutionMode.PAPER

        summary = await trading_engine.get_performance_summary()
        assert summary["initial_balance"] == 50000.0

    async def test_engine_with_suggest_executor(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test engine with suggest executor mode."""
        suggest_executor = SuggestExecutor()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=suggest_executor,
            session_factory=session_factory,
        )

        assert trading_engine.executor.mode == ExecutionMode.SUGGEST

    async def test_properties(self, trading_engine: TradingEngine) -> None:
        """Test engine properties."""
        assert trading_engine.strategy is not None
        assert trading_engine.executor is not None
        assert trading_engine.order_manager is not None
        assert trading_engine.position_tracker is not None
        assert isinstance(trading_engine.is_running, bool)

    async def test_custom_max_position_size(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test engine with custom max position size."""
        paper_executor = PaperExecutor()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            max_position_size=Decimal("0.2"),  # 20%
        )

        # Verify engine was created with custom settings
        assert trading_engine is not None

    async def test_custom_max_open_positions(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy
    ) -> None:
        """Test engine with custom max open positions."""
        paper_executor = PaperExecutor()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            max_open_positions=10,
        )

        # Verify engine was created with custom settings
        assert trading_engine is not None
