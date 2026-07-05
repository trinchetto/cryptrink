"""Settings screen — connections & credentials for external systems.

Read-only status view: it shows which external-system credentials Cryptrink has
detected and which are missing, with a short tooltip on each explaining what it is
and the environment variable / Space secret that sets it. Nothing here mutates
config — values come from the environment / config files at startup.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.web.live_setup import has_revolutx_credentials
from cryptrink.web.state import get_runtime

if TYPE_CHECKING:
    from cryptrink.core.config import Settings


CREDENTIALS_NOTE = (
    "Credentials are read from the environment / Space secrets at startup — this screen is "
    "read-only. On Hugging Face, set them under <b>Settings → Secrets</b>, then reload the Space."
)


def mask_secret(value: str) -> str:
    """Mask a secret, revealing only the last 4 characters (``not set`` if empty)."""
    if not value:
        return "not set"
    return "••••••" + value[-4:]


def credential_rows(settings: Settings) -> list[tuple[str, bool, str, str]]:
    """Return ``(label, detected, detail, tooltip)`` rows for the credentials card.

    ``detected`` drives the ✓/✗ signal; ``detail`` is the masked/short value shown when
    present; ``tooltip`` explains the credential and the env var that sets it.
    """
    revolutx = settings.revolutx
    api_key = revolutx.api_key.get_secret_value()
    has_private = bool(revolutx.private_key.get_secret_value()) or bool(revolutx.private_key_path)
    webhook = settings.notifications.discord_webhook_url.get_secret_value()
    return [
        (
            "Revolut X API key",
            bool(api_key),
            mask_secret(api_key),
            "Your Revolut X API key, required to reach the exchange. "
            "Set the REVOLUTX_API_KEY environment variable (on Hugging Face: Settings → Secrets).",
        ),
        (
            "Revolut X private key",
            has_private,
            "loaded" if has_private else "not set",
            "Ed25519 key used to sign requests. Set REVOLUTX_PRIVATE_KEY (base64-encoded seed) "
            "or REVOLUTX_PRIVATE_KEY_PATH (path to a PEM file).",
        ),
        (
            "Discord webhook",
            bool(webhook),
            "configured" if webhook else "not set",
            "Optional alerts channel for trades and heartbeats. Set NOTIFY_DISCORD_WEBHOOK_URL "
            "and NOTIFY_DISCORD_ENABLED=true.",
        ),
    ]


def _info(tooltip: str) -> str:
    """Render a small ``ⓘ`` help marker with a native hover tooltip."""
    return f'<span class="ck-info" title="{html.escape(tooltip)}">&#9432;</span>'


def _cred_row(label: str, detected: bool, detail: str, tooltip: str) -> str:
    """Render one credential status row: label + ⓘ tooltip, and a ✓/✗ detected signal."""
    if detected:
        status = '<span class="ck-pos">&#10003; detected</span>'
        value = f' · <span class="ck-mono">{html.escape(detail)}</span>' if detail else ""
    else:
        status = '<span style="color:var(--faint)">&#10007; not set</span>'
        value = ""
    return (
        '<div class="ck-kv-row">'
        f'<span style="color:var(--faint)">{html.escape(label)} {_info(tooltip)}</span>'
        f"<span>{status}{value}</span>"
        "</div>"
    )


def _plain_row(label: str, value: str, tooltip: str) -> str:
    """Render an informational (non-credential) row — no ✓/✗ signal."""
    return (
        '<div class="ck-kv-row">'
        f'<span style="color:var(--faint)">{html.escape(label)} {_info(tooltip)}</span>'
        f'<span class="ck-mono">{html.escape(value)}</span></div>'
    )


def _credentials_html(settings: Settings) -> str:
    live_ready = has_revolutx_credentials(settings)
    rows = "".join(_cred_row(*row) for row in credential_rows(settings))
    rows += _plain_row(
        "Revolut X base URL",
        settings.revolutx.base_url,
        "API base URL. Defaults to the production endpoint; override with REVOLUTX_BASE_URL.",
    )
    if live_ready:
        ready = '<span class="ck-pos">&#10003; unlocked</span>'
    else:
        ready = '<span style="color:var(--faint)">paper only — add API key + private key</span>'
    rows += (
        '<div class="ck-kv-row">'
        '<span style="color:var(--faint)">Live (real-money) trading '
        f"{_info('Live trading unlocks once both the Revolut X API key and private key are detected.')}"
        f"</span><span>{ready}</span></div>"
    )
    return (
        '<div class="ck-card"><div class="ck-section-label">Connections &amp; credentials</div>'
        f'<div class="ck-cred-note">{CREDENTIALS_NOTE}</div>{rows}</div>'
    )


def render() -> None:
    """Render the Settings screen panel inside the workspace shell."""
    settings = get_runtime().settings
    with gr.Row(elem_classes=["ck-screen-cols"]), gr.Column(elem_classes=["ck-col-main"]):
        gr.HTML(_credentials_html(settings))
