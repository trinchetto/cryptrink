"""Dashboard screen — at-a-glance engine state, positions, and orders.

Stub: the workspace shell mounts ``render()``; the real metrics + tables land in the
dashboard task. Reuses ``web.tabs.status`` data builders rather than new engine code.
"""

from __future__ import annotations

import gradio as gr


def render() -> None:
    """Build the Dashboard screen panel (placeholder)."""
    gr.Markdown("Dashboard — coming up.")
