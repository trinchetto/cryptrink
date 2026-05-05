"""Gradio web app for Cryptrink (HF Spaces deployment).

The :func:`build_demo` symbol is intentionally not re-exported here because
:mod:`cryptrink.web.app` imports :mod:`gradio`, which lives behind the
``[web]`` extra. Importing this package eagerly triggered the gradio import
chain and broke environments (CI, bare ``pip install cryptrink``) that ship
without the extra. Use ``from cryptrink.web.app import build_demo`` directly.
"""
