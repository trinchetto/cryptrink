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
    # ssr_mode=False: gradio 6.x enables server-side rendering when Node is present
    # (the HF Spaces image installs it), which starts a Node proxy in front of the
    # Python server. Inside the HF container that proxy fails gradio's own
    # localhost-reachability check and crashes launch with "When localhost is not
    # accessible, a shareable link must be created." SSR is only a first-paint
    # optimisation, so disable it and serve the Python app directly.
    demo.launch(ssr_mode=False)
