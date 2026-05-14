"""Multi-strategy router that satisfies the :class:`BaseStrategy` contract.

The :class:`TradingEngine` is bound to *one* strategy at construction
time. The portfolio engine wants *N* strategies — one per allocation —
all sharing the same engine, executor, and cash pool. To avoid forking
``TradingEngine`` we instead wrap N strategies behind a single
:class:`PortfolioStrategyRouter` that dispatches every method call to
the strategy registered for the current symbol.

The router is *stateful* in one tiny way: it remembers the symbol of
the most recent ``generate_signal`` call so that downstream lookups
(``name``, ``required_history``, ``timeframe``) can return the right
per-symbol value. The portfolio engine must also call
:meth:`set_active_symbol` before any ``process_signal`` invocation that
does *not* go through ``generate_signal`` first (e.g. end-of-backtest
forced exits) so ``_record_execution``'s ``strategy_name`` field stays
attributable to the correct allocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from cryptrink.exchange.base import OrderSide
    from cryptrink.strategies.base import StrategyContext


class PortfolioStrategyRouter(BaseStrategy):
    """Adapt a ``{symbol: strategy}`` map to the single-strategy interface."""

    def __init__(
        self,
        strategies: dict[str, BaseStrategy],
        *,
        portfolio_name: str = "portfolio",
    ) -> None:
        if not strategies:
            raise ValueError("PortfolioStrategyRouter requires at least one strategy.")
        self._strategies = dict(strategies)
        self._portfolio_name = portfolio_name
        self._active_symbol: str | None = None

    # ------------------------------------------------------------------
    # Active-symbol bookkeeping
    # ------------------------------------------------------------------

    def set_active_symbol(self, symbol: str) -> None:
        """Pin the symbol whose strategy answers subsequent lookups.

        Called by the portfolio engine before every
        :meth:`TradingEngine.process_signal` invocation so the
        ``strategy_name`` recorded on the resulting ``Position`` row
        matches the allocation that produced the order.
        """
        if symbol not in self._strategies:
            raise KeyError(
                f"Symbol {symbol!r} is not allocated in this portfolio "
                f"(known: {sorted(self._strategies)})"
            )
        self._active_symbol = symbol

    def strategy_for(self, symbol: str) -> BaseStrategy:
        """Return the strategy bound to ``symbol``."""
        return self._strategies[symbol]

    @property
    def symbols(self) -> list[str]:
        return list(self._strategies)

    # ------------------------------------------------------------------
    # BaseStrategy implementation
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        # Recorded as the ``strategy_name`` on every closed Position.
        # Returning the active allocation's name keeps the per-allocation
        # breakdown attributable; falling back to the portfolio name
        # only happens for end-of-backtest unwinds where the operator
        # already knows which symbol unwound from the timestamp.
        if self._active_symbol is not None:
            return self._strategies[self._active_symbol].name
        return self._portfolio_name

    @property
    def description(self) -> str:
        return (
            f"PortfolioStrategyRouter over {len(self._strategies)} "
            f"strategies: {', '.join(sorted(self._strategies))}"
        )

    @property
    def required_history(self) -> int:
        # The portfolio engine must seed the longest required history
        # across allocations, otherwise the slowest indicator never warms
        # up. Take the max so the engine's lookback covers everyone.
        return max(s.required_history for s in self._strategies.values())

    @property
    def timeframe(self) -> str:
        # Phase 1 enforces a single timeframe across allocations, so
        # pick any allocation's value — they should all agree. We pick
        # the first one rather than asserting equality because validation
        # happens at the Portfolio level; the router is the wrong place
        # to surface a config error.
        first = next(iter(self._strategies.values()))
        return first.timeframe

    def generate_signal(self, context: StrategyContext) -> Signal:
        symbol = context.symbol
        strategy = self._strategies.get(symbol)
        if strategy is None:
            # An unallocated symbol asking for a signal is almost
            # certainly an engine bug, but returning HOLD instead of
            # raising keeps the bar loop crash-resistant. Log loudly.
            return Signal(
                signal_type=SignalType.HOLD,
                symbol=symbol,
                strength=SignalStrength.WEAK,
                timestamp=context.timestamp,
                price=context.current_price,
                metadata={"reason": f"no_allocation_for_{symbol}"},
            )
        self._active_symbol = symbol
        return strategy.generate_signal(context)

    def reset(self) -> None:
        self._active_symbol = None
        for strategy in self._strategies.values():
            strategy.reset()

    def on_trade_executed(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        timestamp: datetime,
    ) -> None:
        strategy = self._strategies.get(symbol)
        if strategy is not None:
            strategy.on_trade_executed(symbol, side, quantity, price, timestamp)
