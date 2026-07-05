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


class TestCredentialRows:
    def test_have_expected_labels(self):
        rows = settings_screen.credential_rows(web_state.get_runtime().settings)
        labels = [label for label, _detected, _detail, _tip in rows]
        assert any("API key" in label for label in labels)
        assert any("private key" in label.lower() for label in labels)
        assert any("discord" in label.lower() for label in labels)

    def test_missing_credentials_are_not_detected(self):
        # The default test settings carry no secrets, so nothing should read as detected.
        rows = settings_screen.credential_rows(web_state.get_runtime().settings)
        assert all(detected is False for _label, detected, _detail, _tip in rows)

    def test_each_row_carries_a_help_tooltip(self):
        rows = settings_screen.credential_rows(web_state.get_runtime().settings)
        # The tooltip must name the env var so the operator knows how to set it.
        assert all("REVOLUTX_" in tip or "NOTIFY_" in tip for *_head, tip in rows)
