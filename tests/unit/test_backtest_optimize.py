"""Tests for ``cryptrink.backtest.optimize``.

Both search modes are exercised here against a synthetic objective —
the runner just returns a fabricated :class:`BacktestMetrics` whose
chosen objective field equals a known function of the params. That
way we can assert the optimizer actually selects the optimum without
running a real backtest, which would be heavyweight and tied to the
data feed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptrink.backtest.metrics import BacktestMetrics
from cryptrink.backtest.optimize import (
    OBJECTIVES,
    OptimizationTrial,
    ParameterRange,
    extract_objective,
    run_grid_search,
    run_tpe_search,
)


def _metrics_with(objective: str, value: float) -> BacktestMetrics:
    """Build a :class:`BacktestMetrics` whose ``objective`` field == value.

    All other fields get neutral defaults — they're not under test
    here. The metric we set varies by objective name so the optimizer
    has something meaningful to compare.
    """
    payload = {
        "total_return": Decimal("0"),
        "total_return_pct": Decimal("0"),
        "annualized_return": Decimal("0"),
        "sharpe_ratio": Decimal("0"),
        "sortino_ratio": Decimal("0"),
        "max_drawdown": Decimal("0"),
        "max_drawdown_duration": 0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": Decimal("0"),
        "profit_factor": Decimal("0"),
        "avg_win": Decimal("0"),
        "avg_loss": Decimal("0"),
        "avg_trade": Decimal("0"),
        "best_trade": Decimal("0"),
        "worst_trade": Decimal("0"),
        "max_win_streak": 0,
        "max_loss_streak": 0,
        "current_streak": 0,
        "total_days": 0,
        "trading_days": 0,
        "starting_equity": Decimal("0"),
        "ending_equity": Decimal("0"),
        "peak_equity": Decimal("0"),
    }
    payload[objective] = Decimal(str(value))
    return BacktestMetrics(**payload)


class TestParameterRange:
    def test_int_grid_includes_endpoints(self) -> None:
        r = ParameterRange("p", int, 5, 9, step=1)
        assert r.grid_values() == [5, 6, 7, 8, 9]

    def test_float_grid_rounds_to_step(self) -> None:
        r = ParameterRange("p", float, 0.0, 0.01, step=0.005)
        values = r.grid_values()
        assert values[0] == pytest.approx(0.0)
        assert values[-1] == pytest.approx(0.01)
        assert len(values) == 3

    def test_step_required_for_grid(self) -> None:
        r = ParameterRange("p", float, 0.0, 1.0)
        with pytest.raises(ValueError, match="step"):
            r.grid_values()

    def test_rejects_inverted_range(self) -> None:
        with pytest.raises(ValueError, match="maximum"):
            ParameterRange("p", float, 5.0, 1.0, step=1.0)


class TestExtractObjective:
    def test_known_objectives(self) -> None:
        m = _metrics_with("sharpe_ratio", 1.23)
        assert extract_objective(m, "sharpe_ratio") == pytest.approx(1.23)

    def test_unknown_objective_raises(self) -> None:
        m = _metrics_with("sharpe_ratio", 1.0)
        with pytest.raises(KeyError):
            extract_objective(m, "not_a_metric")


class TestGridSearch:
    @pytest.mark.asyncio
    async def test_picks_maximum_for_maximize_objectives(self) -> None:
        # Strictly increasing in both a and b so the maximum is unique.
        async def runner(params: dict[str, float | int]) -> BacktestMetrics:
            value = float(params["a"]) + float(params["b"]) * 0.01
            return _metrics_with("total_return_pct", value)

        result = await run_grid_search(
            runner=runner,
            ranges=[
                ParameterRange("a", int, 1, 5, step=1),
                ParameterRange("b", int, 0, 2, step=1),
            ],
            objective="total_return_pct",
        )
        assert result.best_params == {"a": 5, "b": 2}
        # 5 * 3 = 15 trials enumerated
        assert len(result.trials) == 15

    @pytest.mark.asyncio
    async def test_picks_minimum_for_max_drawdown_objective(self) -> None:
        async def runner(params: dict[str, float | int]) -> BacktestMetrics:
            return _metrics_with("max_drawdown", float(params["a"]) / 10)

        result = await run_grid_search(
            runner=runner,
            ranges=[ParameterRange("a", int, 1, 5, step=1)],
            objective="max_drawdown",
        )
        # max_drawdown is "minimize" in OBJECTIVES, so a=1 wins.
        assert OBJECTIVES["max_drawdown"][0] == "minimize"
        assert result.best_params == {"a": 1}

    @pytest.mark.asyncio
    async def test_failed_trials_are_recorded_but_skipped(self) -> None:
        # Half the trials raise ValueError (simulating strategy
        # validation rejecting an invalid combo); the optimizer should
        # still pick the best of the survivors.
        async def runner(params: dict[str, float | int]) -> BacktestMetrics:
            if params["a"] % 2 == 0:
                raise ValueError("invalid combo")
            return _metrics_with("total_return_pct", float(params["a"]))

        result = await run_grid_search(
            runner=runner,
            ranges=[ParameterRange("a", int, 1, 5, step=1)],
            objective="total_return_pct",
        )
        assert result.best_params == {"a": 5}
        assert len(result.trials) == 5
        failed = [t for t in result.trials if t.error is not None]
        assert len(failed) == 2

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_for_every_trial(self) -> None:
        seen: list[OptimizationTrial] = []

        async def runner(params: dict[str, float | int]) -> BacktestMetrics:
            return _metrics_with("total_return_pct", float(params["a"]))

        def cb(_i: int, total: int, trial: OptimizationTrial) -> None:
            assert total == 3
            seen.append(trial)

        await run_grid_search(
            runner=runner,
            ranges=[ParameterRange("a", int, 1, 3, step=1)],
            objective="total_return_pct",
            progress_callback=cb,
        )
        assert [t.trial_number for t in seen] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_combinatorial_cap_enforced(self) -> None:
        async def runner(_params: dict[str, float | int]) -> BacktestMetrics:
            return _metrics_with("total_return_pct", 0.0)

        with pytest.raises(ValueError, match="Grid would evaluate"):
            await run_grid_search(
                runner=runner,
                # 100 * 100 = 10_000 combos > MAX_GRID_COMBINATIONS (5_000).
                ranges=[
                    ParameterRange("a", int, 1, 100, step=1),
                    ParameterRange("b", int, 1, 100, step=1),
                ],
                objective="total_return_pct",
            )


class TestTPESearch:
    @pytest.mark.asyncio
    async def test_tpe_finds_optimum_on_simple_objective(self) -> None:
        # Objective peaks at a=8; with seeded TPE and 30 trials the
        # winner is overwhelmingly close to the optimum.
        async def runner(params: dict[str, float | int]) -> BacktestMetrics:
            value = -((float(params["a"]) - 8.0) ** 2)
            return _metrics_with("sharpe_ratio", value)

        result = await run_tpe_search(
            runner=runner,
            ranges=[ParameterRange("a", int, 0, 15)],
            objective="sharpe_ratio",
            n_trials=30,
            seed=7,
        )
        assert abs(int(result.best_params["a"]) - 8) <= 1
        assert len(result.trials) == 30
