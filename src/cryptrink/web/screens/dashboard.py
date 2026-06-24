"""Dashboard screen — at-a-glance engine state, open positions, and orders.

A read-only aggregation of data the Status tab already surfaced: it reuses
``web.tabs.status.refresh`` (engines / orders / positions DataFrames) and derives a
4-up metrics row. No new engine logic. Auto-refreshes on a timer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.web import components
from cryptrink.web.components import euro
from cryptrink.web.state import get_active_screen
from cryptrink.web.tabs import status

if TYPE_CHECKING:
    import pandas as pd


def metrics_html(
    account_equity: str,
    open_pnl: str,
    realised: str,
    active_engines: str,
    *,
    open_positions_sub: str = "",
    realised_sub: str = "",
    engines_sub: str = "",
) -> str:
    """Render the 4-up dashboard metrics row from pre-formatted values."""
    cards = "".join(
        [
            components.metric_card("Account equity", account_equity, "across engines"),
            components.metric_card("Open P&L", open_pnl, open_positions_sub),
            components.metric_card("Realised", realised, realised_sub),
            components.metric_card("Active engines", active_engines, engines_sub),
        ]
    )
    return f'<div class="ck-metrics">{cards}</div>'


def derive_metrics(engines: pd.DataFrame, positions: pd.DataFrame) -> dict[str, str]:
    """Derive the dashboard metric values from the status DataFrames."""
    running = int(engines["running"].sum()) if "running" in engines and len(engines) else 0
    total_engines = len(engines)
    if "current_balance" in engines and len(engines):
        account_equity = euro(float(engines["current_balance"].sum()))
    else:
        account_equity = "—"

    open_mask = positions["status"] == "open" if "status" in positions and len(positions) else None
    open_count = int(open_mask.sum()) if open_mask is not None else 0
    open_pnl_val = (
        float(positions.loc[open_mask, "realized_pnl"].sum())
        if open_mask is not None and "realized_pnl" in positions
        else 0.0
    )
    closed_mask = (
        positions["status"] == "closed" if "status" in positions and len(positions) else None
    )
    realised_val = (
        float(positions.loc[closed_mask, "realized_pnl"].sum())
        if closed_mask is not None and "realized_pnl" in positions
        else 0.0
    )
    closed_count = int(closed_mask.sum()) if closed_mask is not None else 0

    return {
        "account_equity": account_equity,
        "open_pnl": euro(open_pnl_val, signed=True),
        "realised": euro(realised_val, signed=True),
        "active_engines": str(running),
        "open_positions_sub": f"{open_count} open",
        "realised_sub": f"{closed_count} recent trades",
        "engines_sub": f"of {total_engines}",
    }


async def refresh() -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Fetch state and return (metrics_html, open_positions_df, recent_orders_df)."""
    engines, orders, positions = await status.refresh()
    m = derive_metrics(engines, positions)
    html_block = metrics_html(
        m["account_equity"],
        m["open_pnl"],
        m["realised"],
        m["active_engines"],
        open_positions_sub=m["open_positions_sub"],
        realised_sub=m["realised_sub"],
        engines_sub=m["engines_sub"],
    )
    return html_block, positions, orders


def render() -> None:
    """Render the Dashboard screen panel inside the workspace shell."""
    metrics_output = gr.HTML(metrics_html("—", "—", "—", "—"))
    with gr.Group(elem_classes=["ck-card"]):
        gr.HTML('<div class="ck-card-title">Open positions</div>')
        positions_output = gr.Dataframe()
    with gr.Group(elem_classes=["ck-card"]):
        gr.HTML('<div class="ck-card-title">Recent orders</div>')
        orders_output = gr.Dataframe()

    outputs = [metrics_output, positions_output, orders_output]

    async def _tick() -> tuple[object, object, object]:
        # Skip the (3-query) DB refresh unless the Dashboard is the visible screen.
        if get_active_screen() != "dashboard":
            return gr.update(), gr.update(), gr.update()
        return await refresh()

    timer = gr.Timer(5.0)
    timer.tick(fn=_tick, inputs=None, outputs=outputs)
