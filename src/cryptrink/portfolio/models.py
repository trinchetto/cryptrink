"""Portfolio + Allocation data model.

A *portfolio* is a list of :class:`Allocation`s that share a single cash
pool, a single timeframe, and a single set of risk limits. Each
allocation pins a strategy + its tuned parameters to one trading
symbol; the portfolio is the unit the operator backtests, tunes, and
(eventually) trades live.

Phase 1 of this work is deliberately small:

* one symbol per allocation (no overlapping strategies on the same
  pair yet),
* a shared timeframe across allocations (the engine event loop
  marches on one bar clock),
* ``weight`` is recorded but does not yet drive position sizing —
  capital allocation falls back to the executor's default 10%-of-cash
  rule. We keep the field on the dataclass so the YAML format is
  forward-compatible with the weight-aware sizing planned for
  Phase 1.5.

Portfolios round-trip through YAML so they live in the repo as
diff-able config files (``data/portfolios/*.yaml``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import yaml

_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def is_valid_name(name: str) -> bool:
    """Return True if ``name`` is a safe portfolio name.

    A portfolio name doubles as a filename stem, so it is restricted to letters,
    digits, ``_`` and ``-``. This excludes path separators and ``.`` / ``..``, so
    a name can never be used to traverse out of the portfolio directory — the
    storage layer relies on this (see :func:`cryptrink.portfolio.storage.portfolio_path`).
    """
    return bool(_NAME_RE.match(name))


@dataclass
class Allocation:
    """A single ``(symbol, strategy, params)`` slot inside a portfolio."""

    symbol: str
    strategy_name: str
    params: dict[str, float | int] = field(default_factory=dict)
    weight: float = 1.0
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        # Decimals don't survive yaml.safe_dump; stick to float / int / str / bool.
        return {
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "params": dict(self.params),
            "weight": float(self.weight),
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Allocation:
        if "symbol" not in data or "strategy" not in data:
            raise ValueError(
                f"Allocation requires 'symbol' and 'strategy' keys, got {sorted(data.keys())}"
            )
        params = data.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"Allocation 'params' must be a mapping, got {type(params).__name__}")
        return cls(
            symbol=str(data["symbol"]),
            strategy_name=str(data["strategy"]),
            params=dict(params),
            weight=float(data.get("weight", 1.0)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class Portfolio:
    """A named collection of :class:`Allocation`s sharing capital + clock."""

    name: str
    timeframe: str
    initial_balance: Decimal
    allocations: list[Allocation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not is_valid_name(self.name):
            raise ValueError(
                f"Portfolio name {self.name!r} must match {_NAME_RE.pattern} "
                "(used as a filename — no spaces or special characters)."
            )
        if self.initial_balance <= 0:
            raise ValueError(
                f"Portfolio {self.name!r}: initial_balance must be > 0, got {self.initial_balance}"
            )

    def enabled_allocations(self) -> list[Allocation]:
        return [a for a in self.allocations if a.enabled]

    def symbols(self) -> list[str]:
        """Symbols used by enabled allocations, preserving order."""
        return [a.symbol for a in self.enabled_allocations()]

    def validate(self) -> list[str]:
        """Return human-readable error strings; empty list means OK.

        Used by the engine and the UI before kicking off a backtest so
        the operator gets one clear list of problems instead of a stack
        trace from the first failure.
        """
        errors: list[str] = []
        if not self.allocations:
            errors.append("Portfolio has no allocations.")
        if not self.enabled_allocations():
            errors.append("Portfolio has no enabled allocations.")

        # Phase 1: each symbol can appear at most once. Multiple strategies
        # on the same pair would step on each other's positions because
        # the executor and TradingEngine track positions by symbol only,
        # not by (symbol, strategy). Lift this restriction in Phase 2 by
        # introducing a strategy-scoped position view.
        seen: dict[str, int] = {}
        for alloc in self.enabled_allocations():
            seen[alloc.symbol] = seen.get(alloc.symbol, 0) + 1
        duplicates = sorted(s for s, n in seen.items() if n > 1)
        if duplicates:
            errors.append(
                "Each symbol may appear in at most one enabled allocation in Phase 1. "
                f"Duplicate symbols: {', '.join(duplicates)}"
            )

        for alloc in self.allocations:
            if alloc.weight < 0:
                errors.append(f"Allocation {alloc.symbol}: weight must be >= 0.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timeframe": self.timeframe,
            # Stringify so YAML keeps the precision you typed, even when
            # the value is a round figure like 10000 (which would
            # otherwise serialize as ``10000`` and reload as ``int``).
            "initial_balance": str(self.initial_balance),
            "allocations": [a.to_dict() for a in self.allocations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Portfolio:
        for required in ("name", "timeframe", "initial_balance"):
            if required not in data:
                raise ValueError(f"Portfolio YAML missing required key: {required!r}")
        raw_allocations = data.get("allocations") or []
        if not isinstance(raw_allocations, list):
            raise ValueError(
                f"Portfolio 'allocations' must be a list, got {type(raw_allocations).__name__}"
            )
        return cls(
            name=str(data["name"]),
            timeframe=str(data["timeframe"]),
            initial_balance=Decimal(str(data["initial_balance"])),
            allocations=[Allocation.from_dict(a) for a in raw_allocations],
        )


def dump_yaml(portfolio: Portfolio) -> str:
    """Serialise a portfolio to a YAML string.

    ``sort_keys=False`` so the on-disk layout follows the dataclass
    order (``name``, ``timeframe``, ``initial_balance``, ``allocations``)
    which is more readable than YAML's default alphabetical sort.
    """
    return yaml.safe_dump(portfolio.to_dict(), sort_keys=False)


def load_yaml(text: str) -> Portfolio:
    """Parse a YAML string into a :class:`Portfolio`."""
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError("Portfolio YAML is empty.")
    if not isinstance(data, dict):
        raise ValueError(f"Portfolio YAML must be a mapping, got {type(data).__name__}")
    return Portfolio.from_dict(data)


def example_portfolio() -> Portfolio:
    """Return a small example portfolio used by the UI's 'New' button.

    Three allocations on the most common pairs at 1h, default params.
    The operator can immediately run a backtest against it; the YAML
    editor lets them tweak from there.
    """
    return Portfolio(
        name="example",
        timeframe="1h",
        initial_balance=Decimal("10000"),
        allocations=[
            Allocation(
                symbol="BTC-EUR",
                strategy_name="rsi_mean_reversion",
                params={"rsi_period": 14},
            ),
            Allocation(
                symbol="ETH-EUR",
                strategy_name="sma_crossover",
                params={"fast_period": 10, "slow_period": 30},
            ),
        ],
    )
