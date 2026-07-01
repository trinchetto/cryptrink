"""Hugging Face Space entrypoint.

This file lives at the repository root because the HF Spaces Gradio SDK looks
for ``app.py`` by default. It defers all wiring to
:func:`cryptrink.web.app.build_demo`.

HF Spaces only runs ``pip install -r requirements.txt`` before launching the
app — it doesn't ``pip install .`` the project. ``requirements.txt`` is not
committed to this repo; it is generated from ``poetry.lock`` at deploy time by
``.github/workflows/sync-to-hf.yml`` and pushed to the Space. We use a
src-layout (``src/cryptrink/...``), so we prepend ``src/`` to ``sys.path`` here
to make the package importable inside the Space. Locally, ``poetry install``
makes cryptrink importable via the venv's site-packages; the sys.path entry is
then redundant but harmless.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cryptrink.web.app import build_demo  # noqa: E402

demo = build_demo()


if __name__ == "__main__":
    # Let gradio use its default SSR mode (on when Node is present, which the HF
    # Spaces image provides). On gradio 6.15 ssr_mode had to be forced off to dodge
    # a launch crash, but that left the /queue/data SSE undelivered on HF (silent
    # hang). On gradio 6.19 we use the HF-native SSR/Node path, which is what HF's
    # proxy expects for streaming. Locally (no Node) gradio falls back to CSR.
    demo.launch()
