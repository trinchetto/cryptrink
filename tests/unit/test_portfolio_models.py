"""Tests for the Portfolio + Allocation dataclasses and YAML round-trip.

The portfolio config is the primary user-facing surface of Phase 1, so
we pin both halves of the contract:

* every dataclass-shaped field round-trips through YAML untouched, and
* :meth:`Portfolio.validate` catches the realistic operator mistakes
  (no allocations, duplicate symbols, bad weight, bad name).

We don't test ``initial_balance == 0`` here because the dataclass
``__post_init__`` raises on instantiation — that's a unit test on
construction, not on ``validate``, and it lives in the basic-construction
section.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptrink.portfolio.models import (
    Allocation,
    Portfolio,
    dump_yaml,
    example_portfolio,
    load_yaml,
)


class TestAllocation:
    def test_round_trip_through_dict(self) -> None:
        original = Allocation(
            symbol="BTC-EUR",
            strategy_name="rsi_mean_reversion",
            params={"rsi_period": 14, "oversold_threshold": 30.0},
            weight=2.5,
            enabled=False,
        )
        restored = Allocation.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_requires_symbol_and_strategy(self) -> None:
        with pytest.raises(ValueError, match="symbol"):
            Allocation.from_dict({"strategy": "x"})
        with pytest.raises(ValueError, match="symbol"):
            Allocation.from_dict({"symbol": "BTC-EUR"})

    def test_from_dict_rejects_non_dict_params(self) -> None:
        with pytest.raises(ValueError, match="params"):
            Allocation.from_dict({"symbol": "BTC-EUR", "strategy": "x", "params": [1, 2]})

    def test_defaults(self) -> None:
        a = Allocation(symbol="BTC-EUR", strategy_name="rsi_mean_reversion")
        assert a.params == {}
        assert a.weight == 1.0
        assert a.enabled is True


class TestPortfolioConstruction:
    def test_initial_balance_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="initial_balance"):
            Portfolio(
                name="bad",
                timeframe="1h",
                initial_balance=Decimal("0"),
                allocations=[],
            )

    def test_name_must_be_filename_safe(self) -> None:
        with pytest.raises(ValueError, match="name"):
            # spaces are not allowed — names are used as filenames.
            Portfolio(
                name="hello world",
                timeframe="1h",
                initial_balance=Decimal("1000"),
            )


class TestPortfolioValidate:
    def _portfolio(self, allocations: list[Allocation]) -> Portfolio:
        return Portfolio(
            name="test",
            timeframe="1h",
            initial_balance=Decimal("10000"),
            allocations=allocations,
        )

    def test_empty_allocations_flagged(self) -> None:
        errors = self._portfolio([]).validate()
        assert any("no allocations" in e for e in errors)

    def test_no_enabled_allocations_flagged(self) -> None:
        errors = self._portfolio(
            [Allocation(symbol="BTC-EUR", strategy_name="x", enabled=False)]
        ).validate()
        assert any("no enabled allocations" in e.lower() for e in errors)

    def test_duplicate_symbols_flagged(self) -> None:
        errors = self._portfolio(
            [
                Allocation(symbol="BTC-EUR", strategy_name="rsi_mean_reversion"),
                Allocation(symbol="BTC-EUR", strategy_name="sma_crossover"),
            ]
        ).validate()
        assert any("BTC-EUR" in e for e in errors)

    def test_disabled_duplicate_is_ok(self) -> None:
        # Disabled allocations don't count against the "one per symbol"
        # rule — that lets the operator A/B two strategies on the same
        # pair by toggling them.
        errors = self._portfolio(
            [
                Allocation(symbol="BTC-EUR", strategy_name="rsi_mean_reversion"),
                Allocation(symbol="BTC-EUR", strategy_name="sma_crossover", enabled=False),
            ]
        ).validate()
        assert errors == []

    def test_negative_weight_flagged(self) -> None:
        errors = self._portfolio(
            [Allocation(symbol="BTC-EUR", strategy_name="x", weight=-1.0)]
        ).validate()
        assert any("weight" in e for e in errors)

    def test_clean_portfolio_returns_empty_errors(self) -> None:
        errors = self._portfolio(
            [
                Allocation(symbol="BTC-EUR", strategy_name="rsi_mean_reversion"),
                Allocation(symbol="ETH-EUR", strategy_name="sma_crossover"),
            ]
        ).validate()
        assert errors == []


class TestYamlRoundTrip:
    def test_example_round_trips_unchanged(self) -> None:
        original = example_portfolio()
        text = dump_yaml(original)
        restored = load_yaml(text)
        assert restored.name == original.name
        assert restored.timeframe == original.timeframe
        assert restored.initial_balance == original.initial_balance
        assert restored.allocations == original.allocations

    def test_initial_balance_keeps_decimal_precision(self) -> None:
        original = Portfolio(
            name="precise",
            timeframe="1h",
            initial_balance=Decimal("12345.67"),
            allocations=[Allocation(symbol="BTC-EUR", strategy_name="x")],
        )
        restored = load_yaml(dump_yaml(original))
        assert restored.initial_balance == Decimal("12345.67")

    def test_load_yaml_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            load_yaml("")

    def test_load_yaml_rejects_non_mapping(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            load_yaml("- 1\n- 2\n")

    def test_load_yaml_requires_keys(self) -> None:
        with pytest.raises(ValueError, match="missing"):
            load_yaml("name: only_name\n")
