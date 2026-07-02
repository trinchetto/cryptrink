"""Top-level Gradio app for the Cryptrink Hugging Face Space."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.core.logging import get_logger
from cryptrink.web import shell, theme
from cryptrink.web.screens import settings
from cryptrink.web.state import get_runtime
from cryptrink.web.tabs import backtest, data, live, portfolio

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
        # Gradio 6 moved css/js/head off the Blocks constructor; inject the fonts +
        # stylesheet as an (invisible) HTML block so it applies regardless of how the
        # app is launched (local `python app.py` vs HF Spaces), and run the boot JS
        # (theme restore + terminal autoscroll) via a load event.
        gr.HTML(
            theme.fonts_head() + f"<style>{theme.build_css()}</style>",
            elem_id="ck-style-inject",
        )
        shell.build_workspace(
            demo,
            {
                # Suggest is rendered inside backtest.render (stacked section) and
                # Dashboard inside live.render, so neither is a top-level screen.
                "backtest": backtest.render,
                "portfolio": portfolio.render,
                "live": live.render,
                "data": data.render,
                "settings": settings.render,
            },
        )
        demo.load(fn=None, js=theme.boot_js())

    return demo  # type: ignore[no-any-return]


__all__ = ["build_demo", "log_credential_status"]
