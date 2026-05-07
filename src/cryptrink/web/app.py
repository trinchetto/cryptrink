"""Top-level Gradio app for the Cryptrink Hugging Face Space."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.core.logging import get_logger
from cryptrink.web.state import get_runtime
from cryptrink.web.tabs import backtest, live, status, suggest

if TYPE_CHECKING:
    from cryptrink.core.config import Settings

logger = get_logger(__name__)


def log_credential_status(settings: Settings) -> None:
    """Emit a non-sensitive boot-time summary of detected credentials.

    Logs only booleans — never the secret values themselves — so the HF
    Space's Logs tab confirms which env vars actually reached the app.
    Useful for diagnosing 'I added a secret but Live mode is still
    hidden' issues.
    """
    revolutx = settings.revolutx
    notifications = settings.notifications
    logger.info(
        "credentials_check",
        revolutx_api_key=bool(revolutx.api_key.get_secret_value()),
        revolutx_private_key=bool(revolutx.private_key.get_secret_value()),
        revolutx_private_key_path=bool(revolutx.private_key_path),
        discord_enabled=notifications.discord_enabled,
        discord_webhook=bool(notifications.discord_webhook_url.get_secret_value()),
        db_url_kind=_classify_db_url(settings.database.url),
    )


def _classify_db_url(url: str) -> str:
    """Return a short tag for the configured DB URL without leaking any path
    that could double as a credential."""
    if url.startswith("sqlite+aiosqlite:///:memory:"):
        return "sqlite-memory"
    if url.startswith("sqlite+aiosqlite:////data/"):
        return "sqlite-persistent"
    if url.startswith("sqlite+aiosqlite:"):
        return "sqlite-file"
    return "other"


def build_demo() -> gr.Blocks:
    """Build the Cryptrink Gradio :class:`Blocks` app.

    The runtime singleton is initialised eagerly so any registry or
    configuration error surfaces at construction time rather than on the
    first request.
    """
    runtime = get_runtime()
    log_credential_status(runtime.settings)

    with gr.Blocks(title="Cryptrink") as demo:
        gr.Markdown(
            "# Cryptrink\n"
            "Crypto trading agent for Revolut X — backtests, suggestions, "
            "live trading, and engine state."
        )
        with gr.Tabs():
            backtest.render()
            suggest.render()
            live.render()
            status.render()

    return demo  # type: ignore[no-any-return]


__all__ = ["build_demo", "log_credential_status"]
