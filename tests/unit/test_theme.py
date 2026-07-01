"""Tests for the workspace theme CSS builder.

These are regression guards for the Hugging Face Spaces "page grows infinitely"
bug: on Spaces the app is embedded in a content-height-driven iframe, and any
``100vh`` (viewport-relative) height on the shell feeds Gradio's iframe-resizer a
value that ratchets up forever (gradio #12089). The shell must size with a
``height:100%`` chain instead. See ``src/cryptrink/web/theme.py``.
"""

from __future__ import annotations

import re

from cryptrink.web import theme


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


class TestIframeSafeHeight:
    def test_no_100vh_declaration_in_shell(self) -> None:
        """No ``100vh`` may appear in an actual CSS declaration (comments may mention it).

        A viewport-relative height on the embedded shell is the infinite-growth trigger.
        """
        css_no_comments = _strip_comments(theme.build_css())
        vh_declarations = re.findall(
            r"[^;{}]*:\s*[^;{}]*100vh[^;{}]*", css_no_comments
        )
        assert vh_declarations == [], f"shell still uses 100vh: {vh_declarations}"

    def test_uses_height_100pct_chain(self) -> None:
        """The shell fills the frame via height:100% off html/body instead."""
        css = _strip_comments(theme.build_css())
        assert "html, body { height: 100%" in css
        assert "gradio-app { background: var(--bg); display: block; height: 100%" in css


class TestPlotlyCap:
    def test_ck_plot_has_hard_height_cap(self) -> None:
        """The defensive ceiling on Plotly wrappers must be present (backstops #9068)."""
        css = _strip_comments(theme.build_css())
        assert ".ck-plot" in css
        assert "max-height: 340px" in css
