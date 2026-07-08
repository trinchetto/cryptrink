"""Tests for the Portfolio tab's pure ``upsert_allocation_yaml`` helper.

This is the connection that lets "tune a pair" drop a pair into the portfolio
without hand-editing YAML. It's pure (no Gradio, no I/O), so we pin its rules
directly: adopt-timeframe-when-empty, append, replace-by-symbol, and the
single-timeframe guard.
"""

from __future__ import annotations

from cryptrink.portfolio.models import load_yaml
from cryptrink.web.tabs.portfolio import upsert_allocation_yaml


class TestUpsertAllocationYaml:
    def test_blank_editor_starts_portfolio_and_adopts_timeframe(self) -> None:
        yaml_text, error = upsert_allocation_yaml(
            "", "BTC-EUR", "1h", "rsi_mean_reversion", {"rsi_period": 14}
        )
        assert error is None
        portfolio = load_yaml(yaml_text)
        assert portfolio.timeframe == "1h"
        assert [a.symbol for a in portfolio.allocations] == ["BTC-EUR"]
        assert portfolio.allocations[0].strategy_name == "rsi_mean_reversion"
        assert portfolio.allocations[0].params == {"rsi_period": 14}

    def test_second_pair_same_timeframe_appends(self) -> None:
        first, _ = upsert_allocation_yaml("", "BTC-EUR", "1h", "rsi_mean_reversion", {})
        second, error = upsert_allocation_yaml(
            first, "ETH-EUR", "1h", "sma_crossover", {"fast_period": 10}
        )
        assert error is None
        portfolio = load_yaml(second)
        assert [a.symbol for a in portfolio.allocations] == ["BTC-EUR", "ETH-EUR"]

    def test_same_symbol_replaces_in_place(self) -> None:
        first, _ = upsert_allocation_yaml(
            "", "BTC-EUR", "1h", "rsi_mean_reversion", {"rsi_period": 14}
        )
        updated, error = upsert_allocation_yaml(
            first, "BTC-EUR", "1h", "sma_crossover", {"fast_period": 20}
        )
        assert error is None
        portfolio = load_yaml(updated)
        # Still one allocation for the symbol — replaced, not duplicated.
        assert [a.symbol for a in portfolio.allocations] == ["BTC-EUR"]
        assert portfolio.allocations[0].strategy_name == "sma_crossover"
        assert portfolio.allocations[0].params == {"fast_period": 20}

    def test_timeframe_mismatch_is_rejected_unchanged(self) -> None:
        first, _ = upsert_allocation_yaml("", "BTC-EUR", "1h", "rsi_mean_reversion", {})
        unchanged, error = upsert_allocation_yaml(first, "ETH-EUR", "1d", "sma_crossover", {})
        assert error is not None
        assert "timeframe" in error.lower()
        # The editor content is returned untouched so nothing is silently dropped.
        assert unchanged == first

    def test_invalid_yaml_is_reported_unchanged(self) -> None:
        garbage = "allocations: [this is: not valid: yaml"
        unchanged, error = upsert_allocation_yaml(
            garbage, "BTC-EUR", "1h", "rsi_mean_reversion", {}
        )
        assert error is not None
        assert unchanged == garbage
