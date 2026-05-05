"""Top-level Gradio app for the Cryptrink Hugging Face Space."""

from __future__ import annotations

import gradio as gr

from cryptrink.web.state import get_runtime
from cryptrink.web.tabs import backtest, status, suggest


def build_demo() -> gr.Blocks:
    """Build the Cryptrink Gradio :class:`Blocks` app.

    The runtime singleton is initialised eagerly so any registry or
    configuration error surfaces at construction time rather than on the
    first request.
    """
    get_runtime()

    with gr.Blocks(title="Cryptrink") as demo:
        gr.Markdown(
            "# Cryptrink\n"
            "Crypto trading agent for Revolut X — backtests, suggestions, and engine state."
        )
        with gr.Tabs():
            backtest.render()
            suggest.render()
            status.render()

    return demo  # type: ignore[no-any-return]


__all__ = ["build_demo"]
