"""Tests for the Settings screen's pure helpers."""

from __future__ import annotations

import pytest

from cryptrink.web import state as web_state
from cryptrink.web.screens import settings as settings_screen


@pytest.fixture(autouse=True)
def _reset():
    web_state.reset_runtime()
    yield
    web_state.reset_runtime()


class TestMaskSecret:
    def test_empty_is_not_set(self):
        assert settings_screen.mask_secret("") == "not set"

    def test_masks_all_but_tail(self):
        assert settings_screen.mask_secret("abcd1234ef") == "••••••34ef"

    def test_short_value(self):
        assert settings_screen.mask_secret("ab") == "••••••ab"


class TestRows:
    def test_connection_rows_have_expected_labels(self):
        rows = settings_screen.connection_rows(web_state.get_runtime().settings)
        labels = [label for label, _, _ in rows]
        assert "API key" in labels
        assert "Base URL" in labels
        assert "Private key" in labels

    def test_risk_rows_have_expected_labels(self):
        rows = settings_screen.risk_rows(web_state.get_runtime().settings)
        labels = [label for label, _ in rows]
        assert any("position" in label.lower() for label in labels)
        assert any("stop" in label.lower() for label in labels)
