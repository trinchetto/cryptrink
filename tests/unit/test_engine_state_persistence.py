"""Unit tests for TradingEngine state persistence and recovery."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cryptrink.execution.engine import TradingEngine
from cryptrink.execution.paper import PaperExecutor
from cryptrink.execution.repository import EngineStateRepository, init_execution_db
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
        from datetime import UTC, datetime

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


class TestEngineStatePersistence:
    """Tests for TradingEngine state persistence and recovery."""

    async def test_engine_has_unique_id(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine is assigned a unique ID."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
        )

        assert trading_engine.engine_id is not None
        assert len(trading_engine.engine_id) > 0

    async def test_engine_accepts_custom_id(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine accepts a custom ID."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        custom_id = "my-custom-engine-id"

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id=custom_id,
        )

        assert trading_engine.engine_id == custom_id

    async def test_save_state_on_start(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine state is saved when starting."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-1",
        )

        await trading_engine.start()

        # Verify state was saved
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-1")

        assert saved_state is not None
        assert saved_state.engine_id == "test-engine-1"
        assert saved_state.is_running is True
        assert saved_state.strategy_name == "DummyStrategy"

    async def test_save_state_on_stop(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine state is saved when stopping."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-2",
        )

        await trading_engine.start()
        await trading_engine.stop()

        # Verify state was saved with is_running=False
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-2")

        assert saved_state is not None
        assert saved_state.is_running is False

    async def test_save_state_on_reset(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine state is saved when resetting."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-3",
            initial_balance=Decimal("10000"),
        )

        await trading_engine.start()

        # Process signals before reset to verify counters are cleared
        await trading_engine.process_signal("BTC-USD", Decimal("50000"))
        await trading_engine.process_signal("BTC-USD", Decimal("51000"))

        # Manually save state to persist the signal counts
        await trading_engine.save_state()

        await trading_engine.reset(initial_balance=Decimal("20000"))

        # Verify state was saved with reset values
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-3")

        assert saved_state is not None
        assert saved_state.is_running is False
        assert saved_state.initial_balance_decimal == Decimal("20000")
        assert saved_state.current_balance_decimal == Decimal("20000")
        # Reset should clear counters
        assert saved_state.signal_count == 0
        assert saved_state.execution_count == 0

    async def test_save_state_manually(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test manually saving engine state."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-4",
        )

        await trading_engine.save_state()

        # Verify state was saved
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-4")

        assert saved_state is not None
        assert saved_state.engine_id == "test-engine-4"

    async def test_load_nonexistent_state(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test loading state that doesn't exist returns None."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        loaded_engine = await TradingEngine.load_state(
            engine_id="nonexistent-engine",
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
        )

        assert loaded_engine is None

    async def test_save_and_load_state(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test saving and loading engine state."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        # Create and configure an engine
        original_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-5",
            initial_balance=Decimal("15000"),
            max_position_size=Decimal("0.2"),
            max_open_positions=3,
        )

        await original_engine.start()
        await original_engine.process_signal("BTC-USD", Decimal("50000"))
        await original_engine.process_signal("ETH-USD", Decimal("3000"))

        # Manually save state to persist the signal counts
        await original_engine.save_state()

        # Load the state into a new engine
        loaded_engine = await TradingEngine.load_state(
            engine_id="test-engine-5",
            strategy=DummyStrategy(),  # New strategy instance
            executor=PaperExecutor(),  # New executor instance
            session_factory=session_factory,
        )

        assert loaded_engine is not None
        assert loaded_engine.engine_id == original_engine.engine_id
        assert loaded_engine.is_running == original_engine.is_running

        # Check that counters were restored
        original_summary = await original_engine.get_performance_summary()
        loaded_summary = await loaded_engine.get_performance_summary()

        assert loaded_summary["signal_count"] == original_summary["signal_count"]
        assert loaded_summary["execution_count"] == original_summary["execution_count"]
        assert loaded_summary["initial_balance"] == original_summary["initial_balance"]
        assert loaded_summary["current_balance"] == original_summary["current_balance"]

    async def test_state_persists_configuration(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that configuration is persisted and restored."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        # Create engine with custom configuration
        original_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-6",
            initial_balance=Decimal("25000"),
            max_position_size=Decimal("0.15"),
            max_open_positions=10,
        )

        await original_engine.save_state()

        # Load the state
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-6")

        assert saved_state is not None
        assert saved_state.initial_balance_decimal == Decimal("25000")
        assert saved_state.max_position_size_decimal == Decimal("0.15")
        assert saved_state.max_open_positions == 10

    async def test_state_updates_on_multiple_saves(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that multiple saves update the same state record."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-7",
        )

        # Save initial state
        await trading_engine.save_state()

        # Process some signals
        await trading_engine.process_signal("BTC-USD", Decimal("50000"))
        await trading_engine.process_signal("BTC-USD", Decimal("51000"))

        # Save again
        await trading_engine.save_state()

        # Verify only one state record exists
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-7")

        assert saved_state is not None
        assert saved_state.signal_count == 2

    async def test_repr_includes_engine_id(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that engine repr includes engine_id."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-repr-engine",
        )

        repr_str = repr(trading_engine)

        assert "test-repr-engine" in repr_str
        assert "TradingEngine" in repr_str

    async def test_state_persists_executor_mode(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that executor mode is persisted."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-8",
        )

        await trading_engine.save_state()

        # Load state
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-8")

        assert saved_state is not None
        assert saved_state.executor_mode == "paper"

    async def test_state_includes_timestamps(
        self, engine: AsyncEngine, dummy_strategy: DummyStrategy, paper_executor: PaperExecutor
    ) -> None:
        """Test that timestamps are recorded in state."""
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        trading_engine = TradingEngine(
            strategy=dummy_strategy,
            executor=paper_executor,
            session_factory=session_factory,
            engine_id="test-engine-9",
        )

        await trading_engine.save_state()

        # Load state
        state_repo = EngineStateRepository(session_factory)
        saved_state = await state_repo.load_state("test-engine-9")

        assert saved_state is not None
        assert saved_state.created_at > 0
        assert saved_state.updated_at > 0
        assert saved_state.created_datetime is not None
        assert saved_state.updated_datetime is not None
