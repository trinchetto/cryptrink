"""Settings screen — connection, default risk limits, and appearance.

Read-only display of the loaded configuration (the rarely-changed knobs pulled out
of the workflow) plus the three theme swatches. Secrets are masked; nothing here
mutates config — values come from environment / config files.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.web import theme
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


def _kv(label: str, value: str, tone: str = "") -> str:
    tone_cls = {"ok": "ck-pos", "dim": ""}.get(tone, "")
    return (
        f'<div class="ck-kv-row"><span style="color:var(--faint)">{html.escape(label)}</span>'
        f'<span class="ck-mono {tone_cls}">{html.escape(value)}</span></div>'
    )


def _connection_html(settings: Settings) -> str:
    rows = "".join(_kv(label, value, tone) for label, value, tone in connection_rows(settings))
    return (
        f'<div class="ck-card"><div class="ck-section-label">Revolut X connection</div>{rows}</div>'
    )


def _risk_html(settings: Settings) -> str:
    rows = "".join(_kv(label, value) for label, value in risk_rows(settings))
    return f'<div class="ck-card"><div class="ck-section-label">Risk defaults</div>{rows}</div>'


_THEME_SWATCHES = (
    ("carbon", "Carbon", "Dark · teal accent"),
    ("slate", "Slate", "Dark · indigo accent"),
    ("daylight", "Daylight", "Light · green accent"),
)


def render() -> None:
    """Render the Settings screen panel inside the workspace shell."""
    settings = get_runtime().settings
    with gr.Row(elem_classes=["ck-screen-cols"]):
        with gr.Column(elem_classes=["ck-col-main"]):
            gr.HTML(_connection_html(settings))
            gr.HTML(_risk_html(settings))
        with (
            gr.Column(scale=0, elem_classes=["ck-col-320"]),
            gr.Group(elem_classes=["ck-card"]),
        ):
            gr.HTML('<div class="ck-section-label">Appearance</div>')
            for name, label, sub in _THEME_SWATCHES:
                btn = gr.Button(f"{label} — {sub}", elem_classes=["ck-btn-secondary"])
                btn.click(fn=None, js=theme.theme_switch_js(name))
