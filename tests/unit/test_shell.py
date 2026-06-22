"""Tests for the web workspace shell: theme tokens/CSS and pure HTML renderers."""

from __future__ import annotations

from cryptrink.web import theme


class TestThemeTokens:
    def test_three_themes_present(self):
        assert set(theme.THEMES) == {"carbon", "slate", "daylight"}

    def test_carbon_is_default(self):
        assert theme.DEFAULT_THEME == "carbon"

    def test_every_theme_defines_the_same_token_keys(self):
        keys = [set(t) for t in theme.THEMES.values()]
        assert all(k == keys[0] for k in keys)
        assert "--accent" in keys[0]
        assert "--bg" in keys[0]
        assert "--live" in keys[0]

    def test_carbon_accent_value(self):
        assert theme.THEMES["carbon"]["--accent"] == "#3fd9a8"

    def test_daylight_is_light(self):
        assert theme.THEMES["daylight"]["--bg"] == "#f4f3ef"

    def test_css_contains_root_and_theme_classes(self):
        css = theme.build_css()
        assert "#ck-root" in css
        assert ".ck-theme-carbon" in css
        assert ".ck-theme-slate" in css
        assert ".ck-theme-daylight" in css
        assert "@keyframes ck-pulse" in css

    def test_css_embeds_carbon_accent(self):
        assert "#3fd9a8" in theme.build_css()

    def test_fonts_head_loads_ibm_plex(self):
        head = theme.fonts_head()
        assert "IBM+Plex+Sans" in head
        assert "IBM+Plex+Mono" in head

    def test_theme_switch_js_targets_root_and_class(self):
        js = theme.theme_switch_js("slate")
        assert "ck-theme-slate" in js
        assert "ck-root" in js


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
