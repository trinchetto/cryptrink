"""Tests for ``BaseStrategy.param_schema`` introspection and overrides.

We pin two things:

* the per-strategy overrides on the three built-in strategies declare
  every numeric ``__init__`` parameter, with bounds that include the
  default value (otherwise the manual UI would refuse the strategy's
  own defaults), and
* the introspection fallback on a vanilla ``BaseStrategy`` subclass
  enumerates only numeric parameters and reads their defaults from the
  signature — so a strategy author who forgets to override
  ``param_schema`` still gets a usable UI.
"""

from __future__ import annotations

import pytest

from cryptrink.strategies.base import (
    BaseStrategy,
    ParameterSpec,
    Signal,
    SignalStrength,
    SignalType,
)
from cryptrink.strategies.mean_reversion import (
    BollingerBandsStrategy,
    RsiMeanReversionStrategy,
)
from cryptrink.strategies.trend_following import SmaCrossoverStrategy


class _IntrospectableStrategy(BaseStrategy):
    """Vanilla strategy used only to exercise the default param_schema."""

    def __init__(
        self,
        a: int = 5,
        b: float = 1.5,
        label: str = "ignored",
        c: int = 3,
    ) -> None:
        self.a = a
        self.b = b
        self.label = label
        self.c = c

    @property
    def name(self) -> str:
        return "introspectable"

    @property
    def description(self) -> str:
        return "test"

    def generate_signal(self, context):  # type: ignore[override]
        from datetime import UTC, datetime
        from decimal import Decimal

        return Signal(
            signal_type=SignalType.HOLD,
            symbol="X",
            strength=SignalStrength.WEAK,
            timestamp=datetime.now(UTC),
            price=Decimal("0"),
        )


class TestIntrospection:
    def test_skips_non_numeric_params(self) -> None:
        specs = _IntrospectableStrategy.param_schema()
        names = [s.name for s in specs]
        assert names == ["a", "b", "c"], (
            "param_schema should skip the ``label: str`` parameter — only "
            "numeric inputs make sense for the auto-tuner UI."
        )

    def test_default_and_type_pulled_from_signature(self) -> None:
        specs = {s.name: s for s in _IntrospectableStrategy.param_schema()}
        assert specs["a"].param_type is int
        assert specs["a"].default == 5
        assert specs["b"].param_type is float
        assert specs["b"].default == pytest.approx(1.5)


class TestBuiltinSchemas:
    """Each builtin must declare bounds compatible with its own defaults."""

    @pytest.mark.parametrize(
        "strategy_cls",
        [RsiMeanReversionStrategy, BollingerBandsStrategy, SmaCrossoverStrategy],
    )
    def test_defaults_are_inside_bounds(self, strategy_cls: type[BaseStrategy]) -> None:
        for spec in strategy_cls.param_schema():
            if spec.minimum is not None:
                assert spec.default >= spec.minimum, (
                    f"{strategy_cls.__name__}.{spec.name} default "
                    f"{spec.default} is below minimum {spec.minimum}"
                )
            if spec.maximum is not None:
                assert spec.default <= spec.maximum, (
                    f"{strategy_cls.__name__}.{spec.name} default "
                    f"{spec.default} is above maximum {spec.maximum}"
                )

    def test_rsi_schema_covers_all_params(self) -> None:
        names = {s.name for s in RsiMeanReversionStrategy.param_schema()}
        assert names == {
            "rsi_period",
            "oversold_threshold",
            "overbought_threshold",
            "extreme_oversold",
            "extreme_overbought",
        }

    def test_sma_schema_covers_all_params(self) -> None:
        names = {s.name for s in SmaCrossoverStrategy.param_schema()}
        assert names == {"fast_period", "slow_period", "signal_threshold"}

    def test_bollinger_schema_covers_all_params(self) -> None:
        names = {s.name for s in BollingerBandsStrategy.param_schema()}
        assert names == {"period", "std_dev", "penetration_threshold"}


class TestParameterSpec:
    def test_coerce_clamps_to_bounds(self) -> None:
        spec = ParameterSpec(name="x", param_type=int, default=10, minimum=2, maximum=20)
        assert spec.coerce(0) == 2
        assert spec.coerce(100) == 20
        assert spec.coerce(15) == 15

    def test_coerce_casts_to_type(self) -> None:
        int_spec = ParameterSpec(name="x", param_type=int, default=1)
        assert isinstance(int_spec.coerce(3.7), int)
        float_spec = ParameterSpec(name="y", param_type=float, default=1.0)
        assert isinstance(float_spec.coerce(3), float)

    def test_display_label_falls_back_to_name(self) -> None:
        spec = ParameterSpec(name="rsi_period", param_type=int, default=14)
        assert spec.display_label == "Rsi period"
        labelled = ParameterSpec(name="rsi_period", param_type=int, default=14, label="RSI window")
        assert labelled.display_label == "RSI window"


class TestRuntimeIntegration:
    """The runtime helper must surface the per-strategy overrides."""

    def test_get_strategy_param_schema_resolves_builtins(self) -> None:
        from cryptrink.runtime import get_strategy_param_schema

        rsi = get_strategy_param_schema("rsi_mean_reversion")
        assert {s.name for s in rsi} == {
            "rsi_period",
            "oversold_threshold",
            "overbought_threshold",
            "extreme_oversold",
            "extreme_overbought",
        }
