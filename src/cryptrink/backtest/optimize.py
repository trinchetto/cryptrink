"""Strategy parameter tuning for the backtest engine.

This module sweeps a strategy's tunable parameters over a search space
and ranks candidates by a chosen metric of :class:`BacktestMetrics`.

Two search modes are exposed:

* :func:`run_grid_search` — exhaustive cartesian product of per-parameter
  ``(minimum, maximum, step)`` ranges. Deterministic, easy to reason
  about, suitable for one-to-three parameters.
* :func:`run_tpe_search` — Tree-structured Parzen Estimator via Optuna.
  Better when the search space is high-dimensional or continuous.

Both modes are driven by an async ``runner`` callback supplied by the
caller. The runner takes a ``params`` dict and returns
:class:`BacktestMetrics` (or ``None`` if the candidate failed to
backtest, e.g. because the parameter combination violated
strategy-internal constraints). Decoupling the optimizer from the
engine factory keeps this module testable in isolation and lets the
web UI inject its own context (data feed, dataset, dates).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product
from typing import TYPE_CHECKING, Literal

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cryptrink.backtest.metrics import BacktestMetrics

logger = get_logger(__name__)


ObjectiveDirection = Literal["maximize", "minimize"]


# Ordered so the UI dropdown defaults to total_return_pct.
OBJECTIVES: dict[str, tuple[ObjectiveDirection, str]] = {
    "total_return_pct": ("maximize", "Total return %"),
    "sharpe_ratio": ("maximize", "Sharpe ratio"),
    "sortino_ratio": ("maximize", "Sortino ratio"),
    "profit_factor": ("maximize", "Profit factor"),
    "max_drawdown": ("minimize", "Max drawdown (minimize)"),
}


def extract_objective(metrics: BacktestMetrics, name: str) -> float:
    """Pull a single float metric out of :class:`BacktestMetrics`.

    Decimal values are converted to ``float`` so Optuna and our grid
    comparisons can use plain arithmetic. Names not in
    :data:`OBJECTIVES` raise ``KeyError``.
    """
    if name not in OBJECTIVES:
        raise KeyError(f"Unknown objective {name!r}; expected one of {list(OBJECTIVES.keys())}")
    value = getattr(metrics, name)
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# Hard cap so a misconfigured grid (tiny step, wide range) cannot lock
# the worker for hours. The UI surfaces a clear error instead.
MAX_GRID_COMBINATIONS = 5_000


@dataclass(frozen=True)
class ParameterRange:
    """Search range for a single strategy parameter.

    For grid search ``step`` is required and the swept values are
    ``minimum, minimum + step, …, maximum`` (inclusive). For TPE
    ``step`` is optional and only used when the underlying parameter is
    integer-typed (Optuna's ``suggest_int`` always uses ``step=1`` by
    default; floats are sampled continuously when ``step`` is None).
    """

    name: str
    param_type: type
    minimum: float
    maximum: float
    step: float | None = None

    def __post_init__(self) -> None:
        if self.maximum < self.minimum:
            raise ValueError(
                f"ParameterRange {self.name!r}: maximum {self.maximum} < minimum {self.minimum}"
            )
        if self.step is not None and self.step <= 0:
            raise ValueError(f"ParameterRange {self.name!r}: step must be > 0, got {self.step}")

    def grid_values(self) -> list[float | int]:
        """Enumerate the discrete values used by grid search."""
        if self.step is None:
            raise ValueError(f"ParameterRange {self.name!r}: step is required for grid search")
        values: list[float | int] = []
        # Use integer arithmetic on a stride counter to avoid float drift.
        # We compute n_steps from float math but iterate by index, which
        # keeps endpoints exact for sensible (min, max, step) triples.
        span = self.maximum - self.minimum
        n_steps = round(span / self.step)
        for i in range(n_steps + 1):
            raw = self.minimum + i * self.step
            if self.param_type is int:
                values.append(round(raw))
            else:
                # Round to a sane number of decimals derived from step.
                # 0.001 → 6 decimals, 1 → 0 decimals.
                decimals = max(0, -round(_log10(self.step)) + 3)
                values.append(round(raw, decimals))
        # Deduplicate while preserving order (int rounding can collapse
        # neighbouring grid points when step < 1).
        seen: set[float | int] = set()
        unique: list[float | int] = []
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            unique.append(v)
        return unique


def _log10(x: float) -> float:
    import math

    return math.log10(x) if x > 0 else 0.0


@dataclass
class OptimizationTrial:
    """A single point in the search."""

    trial_number: int
    params: dict[str, float | int]
    objective_value: float | None  # None when the backtest failed
    metrics: BacktestMetrics | None
    error: str | None = None


@dataclass
class OptimizationResult:
    """Outcome of a full optimization run."""

    best_params: dict[str, float | int]
    best_objective: float
    best_metrics: BacktestMetrics
    trials: list[OptimizationTrial]
    objective: str
    direction: ObjectiveDirection
    mode: Literal["grid", "tpe"]


@dataclass
class _RunnerContext:
    """Internal helper keeping bookkeeping out of the runners."""

    objective: str
    direction: ObjectiveDirection
    progress_callback: Callable[[int, int, OptimizationTrial], Awaitable[None] | None] | None
    trials: list[OptimizationTrial] = field(default_factory=list)


async def _evaluate(
    runner: Callable[[dict[str, float | int]], Awaitable[BacktestMetrics | None]],
    params: dict[str, float | int],
    trial_number: int,
    total: int,
    ctx: _RunnerContext,
) -> OptimizationTrial:
    """Run the user-supplied backtest runner and record the result."""
    metrics: BacktestMetrics | None = None
    objective_value: float | None = None
    error: str | None = None
    try:
        metrics = await runner(params)
        if metrics is not None:
            objective_value = extract_objective(metrics, ctx.objective)
    except (ValueError, TypeError) as exc:
        # Strategy parameter validation usually raises ValueError; we keep
        # the trial in the result but mark it as failed. Other exceptions
        # propagate because they are likely bugs.
        error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "optimize_trial_failed",
            trial=trial_number,
            params=params,
            error=error,
        )

    trial = OptimizationTrial(
        trial_number=trial_number,
        params=params,
        objective_value=objective_value,
        metrics=metrics,
        error=error,
    )
    ctx.trials.append(trial)
    if ctx.progress_callback is not None:
        result = ctx.progress_callback(trial_number, total, trial)
        if result is not None:
            await result
    return trial


def _select_best(
    trials: list[OptimizationTrial], direction: ObjectiveDirection
) -> OptimizationTrial:
    """Pick the best trial by objective; raise if every trial failed."""
    successful = [t for t in trials if t.objective_value is not None and t.metrics is not None]
    if not successful:
        raise RuntimeError(
            "Optimization produced no successful trials — every parameter combination failed."
        )
    if direction == "maximize":
        return max(successful, key=lambda t: t.objective_value or float("-inf"))
    return min(successful, key=lambda t: t.objective_value or float("inf"))


async def run_grid_search(
    runner: Callable[[dict[str, float | int]], Awaitable[BacktestMetrics | None]],
    ranges: list[ParameterRange],
    objective: str,
    progress_callback: Callable[[int, int, OptimizationTrial], Awaitable[None] | None]
    | None = None,
) -> OptimizationResult:
    """Exhaustively backtest every cartesian combination of ``ranges``.

    Args:
        runner: Async callable that runs one backtest with the supplied
            params and returns its :class:`BacktestMetrics`. Returning
            ``None`` (or raising :class:`ValueError`) marks the trial as
            failed but does not stop the sweep.
        ranges: One :class:`ParameterRange` per tunable parameter. Each
            must have ``step`` set.
        objective: Key into :data:`OBJECTIVES`.
        progress_callback: Optional callback invoked after every trial
            with ``(trial_number, total, trial)``.

    Returns:
        :class:`OptimizationResult` with ``best_params`` selected by
        ``OBJECTIVES[objective]``'s direction.
    """
    if not ranges:
        raise ValueError("grid search requires at least one ParameterRange")
    direction, _ = OBJECTIVES[objective]

    grids = [r.grid_values() for r in ranges]
    total = 1
    for g in grids:
        total *= len(g)
    if total > MAX_GRID_COMBINATIONS:
        raise ValueError(
            f"Grid would evaluate {total} combinations (cap is {MAX_GRID_COMBINATIONS}). "
            "Tighten the ranges or increase the step."
        )
    if total == 0:
        raise ValueError("Grid is empty — every range produced zero values.")

    logger.info(
        "optimize_grid_started",
        objective=objective,
        direction=direction,
        total_combinations=total,
        params=[r.name for r in ranges],
    )

    ctx = _RunnerContext(
        objective=objective, direction=direction, progress_callback=progress_callback
    )
    for i, combo in enumerate(product(*grids), start=1):
        params = {r.name: r.param_type(v) for r, v in zip(ranges, combo, strict=True)}
        await _evaluate(runner, params, i, total, ctx)

    best = _select_best(ctx.trials, direction)
    assert best.metrics is not None and best.objective_value is not None
    logger.info(
        "optimize_grid_finished",
        best_objective=best.objective_value,
        best_params=best.params,
    )
    return OptimizationResult(
        best_params=best.params,
        best_objective=best.objective_value,
        best_metrics=best.metrics,
        trials=ctx.trials,
        objective=objective,
        direction=direction,
        mode="grid",
    )


async def run_tpe_search(
    runner: Callable[[dict[str, float | int]], Awaitable[BacktestMetrics | None]],
    ranges: list[ParameterRange],
    objective: str,
    n_trials: int,
    progress_callback: Callable[[int, int, OptimizationTrial], Awaitable[None] | None]
    | None = None,
    seed: int | None = 42,
) -> OptimizationResult:
    """Bayesian-style search via Optuna's TPE sampler.

    Uses Optuna's ``ask()`` / ``tell()`` API so we can drive the sampler
    from inside an asyncio loop without spawning a thread. Every trial
    awaits the user-supplied runner directly.

    Args:
        runner: As in :func:`run_grid_search`.
        ranges: One :class:`ParameterRange` per tunable parameter.
            ``step`` is optional; when set on a float range it is
            forwarded to Optuna's ``suggest_float``.
        objective: Key into :data:`OBJECTIVES`.
        n_trials: Number of trials to run (must be > 0).
        progress_callback: Optional callback after every trial.
        seed: Sampler seed for reproducibility (``None`` disables seeding).

    Returns:
        :class:`OptimizationResult`.
    """
    if not ranges:
        raise ValueError("TPE search requires at least one ParameterRange")
    if n_trials <= 0:
        raise ValueError(f"n_trials must be > 0, got {n_trials}")

    try:
        import optuna
        from optuna.samplers import TPESampler
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "TPE search requires the 'optuna' package. Install it with `pip install optuna`."
        ) from exc

    direction, _ = OBJECTIVES[objective]

    # Optuna's verbose default logger floods the structlog terminal.
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        direction=direction,
        sampler=TPESampler(seed=seed),
    )
    logger.info(
        "optimize_tpe_started",
        objective=objective,
        direction=direction,
        n_trials=n_trials,
        params=[r.name for r in ranges],
    )

    ctx = _RunnerContext(
        objective=objective, direction=direction, progress_callback=progress_callback
    )
    for i in range(1, n_trials + 1):
        opt_trial = study.ask()
        params: dict[str, float | int] = {}
        for r in ranges:
            if r.param_type is int:
                params[r.name] = opt_trial.suggest_int(r.name, int(r.minimum), int(r.maximum))
            else:
                params[r.name] = opt_trial.suggest_float(
                    r.name, float(r.minimum), float(r.maximum), step=r.step
                )

        trial = await _evaluate(runner, params, i, n_trials, ctx)

        if trial.objective_value is None:
            # Tell Optuna the trial failed so it doesn't bias the surrogate
            # toward this region.
            study.tell(opt_trial, state=optuna.trial.TrialState.FAIL)
        else:
            study.tell(opt_trial, trial.objective_value)

    best = _select_best(ctx.trials, direction)
    assert best.metrics is not None and best.objective_value is not None
    logger.info(
        "optimize_tpe_finished",
        best_objective=best.objective_value,
        best_params=best.params,
    )
    return OptimizationResult(
        best_params=best.params,
        best_objective=best.objective_value,
        best_metrics=best.metrics,
        trials=ctx.trials,
        objective=objective,
        direction=direction,
        mode="tpe",
    )
