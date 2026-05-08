"""Strategy parameter UI + auto-tuning helpers for the Backtest tab.

This module is sliced out of :mod:`cryptrink.web.tabs.backtest` because
the parameter / optimisation surface area is non-trivial (per-strategy
manual inputs, a per-strategy tuning configuration, and an Optuna /
grid search runner) and would otherwise drown the relatively simple
"replay one backtest" wiring already there.

Design notes:

* **Static panels, dynamic visibility.** Gradio event handlers need a
  fixed input/output list at component-definition time, so we render
  *all* strategies' inputs up front and toggle ``visible`` on the
  enclosing :class:`gradio.Group` based on the strategy dropdown.
  ``run_backtest`` and ``run_optimization`` therefore receive a flat
  tuple of every parameter input across every strategy and slice out
  the relevant ones via :func:`decode_manual_params` /
  :func:`decode_tuning_ranges`.
* **Schema-driven.** Each strategy declares its tunable parameters via
  :meth:`BaseStrategy.param_schema`. The bounds defined there feed the
  manual ``gr.Number`` inputs *and* the default tuning ranges, so a
  strategy author touches one file to expose a new parameter
  end-to-end.
* **Apply best params.** After an optimisation run we keep the best
  parameter dict in a :class:`gradio.State`. The "Apply best to manual"
  button unpacks that dict back into the manual ``gr.Number`` inputs of
  the currently selected strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import gradio as gr
import pandas as pd

from cryptrink.backtest.engine import BacktestEngine
from cryptrink.backtest.optimize import (
    OBJECTIVES,
    OptimizationResult,
    OptimizationTrial,
    ParameterRange,
    run_grid_search,
    run_tpe_search,
)
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCVRepository
from cryptrink.runtime import get_strategy_param_schema, resolve_strategy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from cryptrink.backtest.metrics import BacktestMetrics
    from cryptrink.strategies.base import ParameterSpec
    from cryptrink.web.state import WebRuntime


# ----------------------------------------------------------------------
# Panel data structures
# ----------------------------------------------------------------------


@dataclass
class ManualPanel:
    """Per-strategy block of ``gr.Number`` inputs for manual tuning."""

    strategy_name: str
    group: gr.Group
    components: list[gr.Number]
    specs: list[ParameterSpec]


@dataclass
class TuningPanel:
    """Per-strategy block of ``[enable, min, max, step]`` rows.

    ``components`` is a flat list of length ``4 * len(specs)`` ordered
    as ``[enable_0, min_0, max_0, step_0, enable_1, min_1, ...]``.
    Keeping the layout flat makes wiring inputs / outputs to Gradio
    handlers straightforward — see :func:`decode_tuning_ranges`.
    """

    strategy_name: str
    group: gr.Group
    components: list[gr.Component]
    specs: list[ParameterSpec]


# ----------------------------------------------------------------------
# Panel rendering
# ----------------------------------------------------------------------


def render_manual_panels(
    strategy_options: list[str],
    default_strategy: str | None,
) -> dict[str, ManualPanel]:
    """Render one parameter input group per strategy.

    Only the panel for ``default_strategy`` is initially visible. The
    Backtest tab wires the strategy dropdown's ``change`` event to
    :func:`visibility_updates` to toggle them.
    """
    panels: dict[str, ManualPanel] = {}
    for name in strategy_options:
        specs = get_strategy_param_schema(name)
        with gr.Group(visible=(name == default_strategy)) as group:
            gr.Markdown(f"**{name} parameters**")
            comps: list[gr.Number] = []
            for spec in specs:
                comps.append(_make_param_input(spec))
        panels[name] = ManualPanel(strategy_name=name, group=group, components=comps, specs=specs)
    return panels


def render_tuning_panels(
    strategy_options: list[str],
    default_strategy: str | None,
) -> dict[str, TuningPanel]:
    """Render one tuning-range group per strategy."""
    panels: dict[str, TuningPanel] = {}
    for name in strategy_options:
        specs = get_strategy_param_schema(name)
        with gr.Group(visible=(name == default_strategy)) as group:
            gr.Markdown(f"**{name} tuning ranges** — tick the parameters to vary.")
            comps: list[gr.Component] = []
            for spec in specs:
                with gr.Row():
                    enable = gr.Checkbox(
                        value=False,
                        label=f"Tune {spec.display_label}",
                        info=spec.help,
                        scale=2,
                    )
                    minimum = gr.Number(
                        value=_default_min(spec),
                        label="Min",
                        precision=_precision(spec),
                    )
                    maximum = gr.Number(
                        value=_default_max(spec),
                        label="Max",
                        precision=_precision(spec),
                    )
                    step = gr.Number(
                        value=spec.step or 1,
                        label="Step (grid)",
                        precision=_precision(spec),
                    )
                comps.extend([enable, minimum, maximum, step])
        panels[name] = TuningPanel(strategy_name=name, group=group, components=comps, specs=specs)
    return panels


def _make_param_input(spec: ParameterSpec) -> gr.Number:
    """Render a single ``gr.Number`` for a strategy parameter."""
    return gr.Number(
        value=spec.default,
        label=spec.display_label,
        info=spec.help,
        minimum=spec.minimum,
        maximum=spec.maximum,
        step=float(spec.step) if spec.step is not None else 1,
        precision=_precision(spec),
    )


def _precision(spec: ParameterSpec) -> int | None:
    """Number of decimal places ``gr.Number`` should accept.

    ``None`` lets Gradio render arbitrary precision; for ``int`` params
    we pin precision to 0 so the input rounds. For floats we derive
    enough decimals from the step (0.1 → 1, 0.001 → 3, 0.0005 → 4).
    """
    if spec.param_type is int:
        return 0
    if spec.step is None:
        return None
    import math

    if spec.step >= 1:
        return 0
    return max(1, -math.floor(math.log10(spec.step)))


def _default_min(spec: ParameterSpec) -> float | int:
    if spec.minimum is not None:
        return spec.minimum
    return spec.default


def _default_max(spec: ParameterSpec) -> float | int:
    if spec.maximum is not None:
        return spec.maximum
    return spec.default


# ----------------------------------------------------------------------
# Visibility / decoding
# ----------------------------------------------------------------------


def visibility_updates(
    strategy_name: str,
    panels: dict[str, ManualPanel] | dict[str, TuningPanel],
) -> list[object]:
    """Return ``gr.update`` calls toggling exactly one panel visible."""
    return [gr.update(visible=(name == strategy_name)) for name in panels]


def flatten_components(
    panels: dict[str, ManualPanel] | dict[str, TuningPanel],
) -> list[gr.Component]:
    """Flatten panels' components in deterministic order for handler wiring."""
    flat: list[gr.Component] = []
    for name in panels:
        flat.extend(panels[name].components)
    return flat


def decode_manual_params(
    strategy_name: str,
    flat_values: tuple[object, ...] | list[object],
    panels: dict[str, ManualPanel],
) -> dict[str, float | int]:
    """Pull the selected strategy's parameter values out of a flat tuple.

    The flat tuple is in the same order as :func:`flatten_components`.
    Values are coerced to the spec's type (``int``/``float``) and
    clamped to declared bounds via :meth:`ParameterSpec.coerce`.
    """
    offset = 0
    for name, panel in panels.items():
        n = len(panel.components)
        if name == strategy_name:
            chunk = list(flat_values[offset : offset + n])
            return {
                spec.name: spec.coerce(value)  # type: ignore[arg-type]
                for spec, value in zip(panel.specs, chunk, strict=True)
            }
        offset += n
    raise KeyError(f"No manual panel for strategy {strategy_name!r}")


def decode_tuning_ranges(
    strategy_name: str,
    flat_values: tuple[object, ...] | list[object],
    panels: dict[str, TuningPanel],
    *,
    require_step: bool,
) -> list[ParameterRange]:
    """Build :class:`ParameterRange` list for the enabled parameters.

    ``flat_values`` matches :func:`flatten_components` of ``panels``.
    Each parameter contributes 4 consecutive entries
    ``(enable, minimum, maximum, step)``.

    If ``require_step`` is True (grid mode), parameters with an empty
    or zero step are rejected with :class:`ValueError`.
    """
    offset = 0
    for name, panel in panels.items():
        n = len(panel.components)
        if name == strategy_name:
            chunk = list(flat_values[offset : offset + n])
            return _build_ranges(panel.specs, chunk, require_step=require_step)
        offset += n
    raise KeyError(f"No tuning panel for strategy {strategy_name!r}")


def _build_ranges(
    specs: list[ParameterSpec],
    chunk: list[object],
    *,
    require_step: bool,
) -> list[ParameterRange]:
    ranges: list[ParameterRange] = []
    for i, spec in enumerate(specs):
        enable = bool(chunk[i * 4])
        if not enable:
            continue
        raw_min = chunk[i * 4 + 1]
        raw_max = chunk[i * 4 + 2]
        raw_step = chunk[i * 4 + 3]
        if raw_min is None or raw_max is None:
            raise ValueError(
                f"Parameter {spec.display_label!r} is enabled for tuning but min or max is empty."
            )
        minimum = float(raw_min)  # type: ignore[arg-type]
        maximum = float(raw_max)  # type: ignore[arg-type]
        step: float | None
        if raw_step in (None, 0, 0.0, ""):
            if require_step:
                raise ValueError(
                    f"Parameter {spec.display_label!r}: step is required for grid search."
                )
            step = None
        else:
            step = float(raw_step)  # type: ignore[arg-type]
        if spec.param_type is int:
            minimum = round(minimum)
            maximum = round(maximum)
        ranges.append(
            ParameterRange(
                name=spec.name,
                param_type=spec.param_type,
                minimum=minimum,
                maximum=maximum,
                step=step,
            )
        )
    if not ranges:
        raise ValueError("No parameters are enabled for tuning — tick at least one before running.")
    return ranges


def manual_value_updates(
    strategy_name: str,
    best_params: dict[str, float | int],
    panels: dict[str, ManualPanel],
) -> list[object]:
    """Build ``gr.update`` calls that push ``best_params`` into the inputs.

    Returns a list aligned with :func:`flatten_components` of ``panels``.
    Components belonging to strategies other than ``strategy_name`` get a
    no-op ``gr.update()`` so their values stay put.
    """
    updates: list[object] = []
    for name, panel in panels.items():
        for spec in panel.specs:
            if name == strategy_name and spec.name in best_params:
                updates.append(gr.update(value=best_params[spec.name]))
            else:
                updates.append(gr.update())
    return updates


# ----------------------------------------------------------------------
# Optimization runner
# ----------------------------------------------------------------------


def _summarise_best(result: OptimizationResult) -> str:
    """Human-readable best-params summary for the markdown panel."""
    metrics = result.best_metrics
    pretty_params = ", ".join(f"`{k}`={v}" for k, v in result.best_params.items())
    obj_label = OBJECTIVES[result.objective][1]
    return (
        f"### Best parameters ({result.mode}, {obj_label} {result.direction})\n\n"
        f"- Params: {pretty_params}\n"
        f"- Objective ({result.objective}): **{result.best_objective:.4f}**\n"
        f"- Total return: {float(metrics.total_return_pct) * 100:+.2f}% "
        f"(€{metrics.total_return:,.2f})\n"
        f"- Sharpe: {float(metrics.sharpe_ratio):.2f} | "
        f"Sortino: {float(metrics.sortino_ratio):.2f} | "
        f"Max drawdown: {float(metrics.max_drawdown) * 100:.2f}%\n"
        f"- Trades: {metrics.total_trades} | "
        f"Win rate: {float(metrics.win_rate) * 100:.1f}% | "
        f"Profit factor: {float(metrics.profit_factor):.2f}\n"
    )


def trials_dataframe(result: OptimizationResult, top_n: int = 25) -> pd.DataFrame:
    """Render the top-``top_n`` trials, sorted by objective."""
    rows: list[dict[str, object]] = []
    successful = [t for t in result.trials if t.objective_value is not None]
    reverse = result.direction == "maximize"
    successful.sort(key=lambda t: t.objective_value or 0.0, reverse=reverse)
    for t in successful[:top_n]:
        assert t.metrics is not None
        row: dict[str, object] = {
            "trial": t.trial_number,
            "objective": round(t.objective_value or 0.0, 6),
            "total_return_pct": round(float(t.metrics.total_return_pct) * 100, 3),
            "sharpe": round(float(t.metrics.sharpe_ratio), 3),
            "max_drawdown_pct": round(float(t.metrics.max_drawdown) * 100, 3),
            "trades": t.metrics.total_trades,
        }
        row.update(t.params)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["trial", "objective"])
    return pd.DataFrame(rows)


def empty_trials_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["trial", "objective"])


def make_runner(
    strategy_name: str,
    base_params: dict[str, float | int],
    runtime: WebRuntime,
    repository: OHLCVRepository,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    initial_capital: float,
) -> Callable[[dict[str, float | int]], Awaitable[BacktestMetrics | None]]:
    """Build the per-trial async callback consumed by the optimizer.

    The callback merges ``base_params`` (the current manual values) with
    the trial's swept params and runs a fresh :class:`BacktestEngine`.
    Returning ``None`` (or letting :class:`ValueError` bubble up, which
    the optimizer catches) marks the trial as failed without aborting
    the sweep.
    """

    async def _runner(params: dict[str, float | int]) -> BacktestMetrics | None:
        merged = {**base_params, **params}
        try:
            strategy = resolve_strategy(strategy_name, **merged)
        except (ValueError, TypeError):
            # The strategy itself rejected the combination — let it
            # surface as a failed trial instead of crashing the run.
            raise
        data_feed = HistoricalDataFeed(repository)
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=data_feed,
            initial_balance=Decimal(str(initial_capital)),
            session_factory=runtime.session_factory,
            risk_settings=runtime.settings.risk,
        )
        try:
            result = await engine.run(
                symbol=symbol,
                start_time=start_dt,
                end_time=end_dt,
                timeframe=timeframe,
            )
        except ValueError:
            # Engine raises ValueError when there's no data in the window
            # for this combo (e.g. required_history pushed lookback past
            # available data). Fail the trial gracefully.
            return None
        return result.metrics

    return _runner


# Outputs of run_optimization, in order:
#   summary_md, terminal_md, trials_df, result_state
async def run_optimization(
    strategy_name: str,
    dataset_value: str | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    mode: Literal["grid", "tpe"],
    objective: str,
    n_trials: int,
    *flat_values: object,
) -> AsyncIterator[tuple[str, str, pd.DataFrame, OptimizationResult | None]]:
    """Stream an optimisation run.

    The ``flat_values`` tuple is split into ``(manual_chunk,
    tuning_chunk)`` — the caller wires inputs in that order. Manual
    values seed every trial (so non-tuned parameters keep their
    operator-chosen value); tuned parameters override them per trial.
    """
    # Imports kept local to dodge a circular import with backtest.py.
    import time

    from cryptrink.web.state import Dataset, get_runtime
    from cryptrink.web.tabs.backtest import (
        _emit,
        _emit_failure,
        _format_elapsed,
        _manual_panels,
        _render_terminal,
        _tuning_panels,
    )

    started = time.perf_counter()

    summary_md = "_(running…)_"
    trials_df = empty_trials_df()
    result_state: OptimizationResult | None = None

    yield (
        summary_md,
        _emit(
            f"optimize: starting (strategy={strategy_name!r}, mode={mode}, objective={objective})"
        ),
        trials_df,
        result_state,
    )

    if not strategy_name or not dataset_value:
        yield (
            summary_md,
            _emit_failure("optimize: strategy and dataset are required"),
            trials_df,
            result_state,
        )
        return

    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure("optimize: malformed dataset value", exc),
            trials_df,
            result_state,
        )
        return

    try:
        from datetime import UTC

        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_date
            else datetime.now(UTC)
        )
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure("optimize: invalid date", exc),
            trials_df,
            result_state,
        )
        return

    if end_dt <= start_dt:
        yield (
            summary_md,
            _emit_failure("optimize: end date must be after start date"),
            trials_df,
            result_state,
        )
        return

    n_manual = sum(len(p.components) for p in _manual_panels.values())
    manual_chunk = flat_values[:n_manual]
    tuning_chunk = flat_values[n_manual:]

    try:
        base_params = decode_manual_params(strategy_name, manual_chunk, _manual_panels)
    except (ValueError, KeyError) as exc:
        yield (
            summary_md,
            _emit_failure("optimize: failed to read manual parameters", exc),
            trials_df,
            result_state,
        )
        return

    try:
        ranges = decode_tuning_ranges(
            strategy_name,
            tuning_chunk,
            _tuning_panels,
            require_step=(mode == "grid"),
        )
    except (ValueError, KeyError) as exc:
        yield (
            summary_md,
            _emit_failure(f"optimize: {exc}"),
            trials_df,
            result_state,
        )
        return

    runtime = get_runtime()
    repository = OHLCVRepository(runtime.session_factory)

    runner = make_runner(
        strategy_name=strategy_name,
        base_params=base_params,
        runtime=runtime,
        repository=repository,
        symbol=symbol,
        timeframe=timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=initial_capital,
    )

    # Progress is communicated via _emit; we can't yield from inside the
    # progress_callback because it's not the generator's frame. Instead
    # we collect a list reference and the runner emits log lines.
    progress_log: list[str] = []

    def _progress(i: int, total: int, trial: OptimizationTrial) -> None:
        if trial.objective_value is None:
            progress_log.append(
                f"optimize: trial {i}/{total} FAILED ({trial.error or 'no metrics'}) "
                f"params={trial.params}"
            )
        else:
            progress_log.append(
                f"optimize: trial {i}/{total} {trial.objective_value:+.4f} params={trial.params}"
            )

    try:
        if mode == "grid":
            yield (
                summary_md,
                _emit(
                    f"optimize: grid sweep over {len(ranges)} parameter(s) "
                    f"({[r.name for r in ranges]})"
                ),
                trials_df,
                result_state,
            )
            result = await run_grid_search(
                runner=runner,
                ranges=ranges,
                objective=objective,
                progress_callback=_progress,
            )
        else:
            yield (
                summary_md,
                _emit(
                    f"optimize: TPE sweep, n_trials={n_trials}, params={[r.name for r in ranges]}"
                ),
                trials_df,
                result_state,
            )
            result = await run_tpe_search(
                runner=runner,
                ranges=ranges,
                objective=objective,
                n_trials=n_trials,
                progress_callback=_progress,
            )
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure(f"optimize: {exc}"),
            trials_df,
            result_state,
        )
        return
    except RuntimeError as exc:
        yield (
            summary_md,
            _emit_failure(f"optimize: {exc}"),
            trials_df,
            result_state,
        )
        return

    log = _render_terminal()
    for line in progress_log:
        log = _emit(line)
    log = _emit(
        f"optimize: COMPLETE — {len(result.trials)} trials in {_format_elapsed(started)}, "
        f"best {result.objective}={result.best_objective:.4f}"
    )

    yield (
        _summarise_best(result),
        log,
        trials_dataframe(result),
        result,
    )


async def apply_best_params(
    strategy_name: str,
    result: OptimizationResult | None,
) -> list[object]:
    """Push the optimisation winner back into the manual inputs.

    Returns a list aligned with :func:`flatten_components` of the manual
    panels — Gradio updates every component, but only the visible
    strategy's matching params actually change value.
    """
    # Local import to dodge circularity (backtest.py imports this module).
    from cryptrink.web.tabs.backtest import _manual_panels

    if result is None:
        return [gr.update() for _ in flatten_components(_manual_panels)]
    return manual_value_updates(strategy_name, result.best_params, _manual_panels)
