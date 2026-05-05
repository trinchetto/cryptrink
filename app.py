"""Hugging Face Space entrypoint.

This file lives at the repository root because the HF Spaces Gradio SDK looks
for ``app.py`` by default. It defers all wiring to
:func:`cryptrink.web.app.build_demo`.
"""

from __future__ import annotations

from cryptrink.web.app import build_demo

demo = build_demo()


if __name__ == "__main__":
    demo.launch()
