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
    def test_nav_items_are_flat_three_sections(self):
        from cryptrink.web import shell

        # Flat, ungrouped nav — three top-level sections in pipeline order.
        assert [item.key for item in shell.NAV_ITEMS] == ["data", "portfolio", "live"]
        assert [item.label for item in shell.NAV_ITEMS] == [
            "Data Management",
            "Portfolio Design",
            "Live Execution",
        ]

    def test_nav_keys_exclude_settings_and_backtest(self):
        from cryptrink.web import shell

        # Only sidebar-visible screens get nav buttons; Settings is header-gear only and
        # Backtest folds into Portfolio Design (no standalone screen).
        assert shell.NAV_KEYS == ["data", "portfolio", "live"]
        assert "settings" not in shell.NAV_KEYS
        assert "backtest" not in shell.NAV_KEYS

    def test_screen_order_has_all_panels_settings_last(self):
        from cryptrink.web import shell

        # Every mounted panel, in pipeline order, with the gear-only Settings panel last.
        # Backtest is not a panel anymore — it renders inside the Portfolio Design screen.
        assert shell.SCREEN_ORDER == [
            "data",
            "portfolio",
            "live",
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
