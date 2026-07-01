"""Settings screen — connection and default risk limits.

Read-only display of the loaded configuration (the rarely-changed knobs pulled out
of the workflow). Secrets are masked; nothing here mutates config — values come
from environment / config files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.web import components
from cryptrink.web.state import get_runtime

if TYPE_CHECKING:
    from cryptrink.core.config import Settings


def mask_secret(value: str) -> str:
    """Mask a secret, revealing only the last 4 characters (``not set`` if empty)."""
    if not value:
        return "not set"
    return "••••••" + value[-4:]


def connection_rows(settings: Settings) -> list[tuple[str, str, str]]:
    """Return ``(label, value, tone)`` rows for the Revolut X connection card.

    ``tone`` is ``"ok"`` | ``"dim"`` and colours the value.
    """
    revolutx = settings.revolutx
    api_key = revolutx.api_key.get_secret_value()
    has_private = bool(revolutx.private_key.get_secret_value()) or bool(revolutx.private_key_path)
    webhook = settings.notifications.discord_webhook_url.get_secret_value()
    return [
        ("API key", mask_secret(api_key), "ok" if api_key else "dim"),
        ("Private key", "loaded" if has_private else "not set", "ok" if has_private else "dim"),
        ("Base URL", revolutx.base_url, "dim"),
        (
            "Discord webhook",
            "configured" if webhook else "not set",
            "ok" if webhook else "dim",
        ),
    ]


def risk_rows(settings: Settings) -> list[tuple[str, str]]:
    """Return ``(label, value)`` rows for the risk-defaults card."""
    risk = settings.risk
    return [
        ("Max position size", f"{risk.max_position_size_pct * 100:.0f}%"),
        ("Risk per trade", f"{risk.risk_per_trade * 100:.1f}%"),
        ("Stop loss", f"{risk.default_stop_loss_pct * 100:.0f}%"),
        ("Take profit", f"{risk.default_take_profit_pct * 100:.0f}%"),
        ("Max open positions", str(risk.max_open_positions)),
    ]


def _connection_html(settings: Settings) -> str:
    rows = "".join(
        components.kv_row(label, value, tone) for label, value, tone in connection_rows(settings)
    )
    return (
        f'<div class="ck-card"><div class="ck-section-label">Revolut X connection</div>{rows}</div>'
    )


def _risk_html(settings: Settings) -> str:
    rows = "".join(components.kv_row(label, value) for label, value in risk_rows(settings))
    return f'<div class="ck-card"><div class="ck-section-label">Risk defaults</div>{rows}</div>'


def render() -> None:
    """Render the Settings screen panel inside the workspace shell."""
    settings = get_runtime().settings
    with gr.Row(elem_classes=["ck-screen-cols"]), gr.Column(elem_classes=["ck-col-main"]):
        gr.HTML(_connection_html(settings))
        gr.HTML(_risk_html(settings))
