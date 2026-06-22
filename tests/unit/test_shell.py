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
