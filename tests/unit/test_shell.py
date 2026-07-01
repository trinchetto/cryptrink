"""Tests for the web workspace shell: theme tokens/CSS and pure HTML renderers."""

from __future__ import annotations

from cryptrink.web import theme


class TestTheme:
    def test_css_declares_carbon_tokens_on_root(self):
        css = theme.build_css()
        assert "#ck-root" in css
        # Carbon tokens are inlined onto #ck-root, not per-theme classes.
        assert "--accent: #3fd9a8;" in css
        assert "--bg: #14171c;" in css
        assert "--live: #ef4658;" in css
        assert "@keyframes ck-pulse" in css

    def test_css_has_no_per_theme_classes(self):
        css = theme.build_css()
        assert ".ck-theme-" not in css

    def test_fonts_head_loads_ibm_plex(self):
        head = theme.fonts_head()
        assert "IBM+Plex+Sans" in head
        assert "IBM+Plex+Mono" in head

    def test_boot_js_forces_dark_and_sticks_terminal(self):
        js = theme.boot_js()
        assert "classList.add('dark')" in js
        assert "ck-term" in js
        # The removed theme-restore branch no longer references localStorage.
        assert "localStorage" not in js


class TestNavModel:
    def test_group_labels(self):
        from cryptrink.web import shell

        assert [g.label for g in shell.NAV_GROUPS] == ["Research", "Trade", "Monitor", "System"]

    def test_screen_order_matches_prototype(self):
        from cryptrink.web import shell

        assert shell.SCREEN_ORDER == [
            "backtest",
            "portfolio",
            "suggest",
            "live",
            "dashboard",
            "data",
            "settings",
        ]

    def test_screen_meta_has_title_and_subtitle(self):
        from cryptrink.web import shell

        title, sub = shell.SCREEN_META["portfolio"]
        assert "Portfolio" in title
        assert sub


class TestTerminalHtml:
    def test_renders_line_fields(self):
        from cryptrink.web import shell
        from cryptrink.web.state import LogEvent

        events = [LogEvent("09:14:02", "sys", "ok", "boot done")]
        html = shell.terminal_html(events)
        assert "boot done" in html
        assert "09:14:02" in html
        assert "sys" in html
        assert "ck-lvl-ok" in html

    def test_escapes_message(self):
        from cryptrink.web import shell
        from cryptrink.web.state import LogEvent

        html = shell.terminal_html([LogEvent("09:14:02", "sys", "ok", "<script>")])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_keeps_cursor(self):
        from cryptrink.web import shell

        html = shell.terminal_html([])
        assert "ck-term-cursor" in html


class TestBannerHtml:
    def test_paper_banner(self):
        from cryptrink.web import shell

        html = shell.banner_html("paper")
        assert "PAPER" in html
        assert "no real orders" in html.lower()
        assert "ck-banner-paper" in html

    def test_live_banner_is_pulsing_red(self):
        from cryptrink.web import shell

        html = shell.banner_html("live")
        assert "LIVE" in html
        assert "ck-pulse" in html
        assert "ck-banner-live" in html


class TestScreenHeaderHtml:
    def test_includes_title_subtitle_and_sync(self):
        from cryptrink.web import shell

        html = shell.screen_header_html("portfolio", "09:41:58")
        assert "Portfolio" in html
        assert "09:41:58" in html

    def test_handles_missing_sync(self):
        from cryptrink.web import shell

        html = shell.screen_header_html("portfolio", None)
        assert "Portfolio" in html
