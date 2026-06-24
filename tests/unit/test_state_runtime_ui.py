"""Tests for the redesign's UI runtime state: mode, shared log buffer, sync stamps."""

from __future__ import annotations

import pytest

from cryptrink.web import state as web_state


@pytest.fixture(autouse=True)
def _reset():
    web_state.reset_runtime()
    yield
    web_state.reset_runtime()


class TestMode:
    def test_default_mode_is_paper(self):
        assert web_state.get_mode() == "paper"

    def test_set_mode_roundtrips(self):
        web_state.set_mode("live")
        assert web_state.get_mode() == "live"

    def test_set_mode_rejects_unknown(self):
        with pytest.raises(ValueError, match="mode"):
            web_state.set_mode("bogus")


class TestLogBuffer:
    def test_starts_empty(self):
        assert web_state.get_log_events() == []

    def test_log_event_appends_with_fields(self):
        web_state.log_event("sys", "ok", "boot done")
        events = web_state.get_log_events()
        assert len(events) == 1
        event = events[0]
        assert event.source == "sys"
        assert event.level == "ok"
        assert event.message == "boot done"
        assert isinstance(event.time, str)
        assert len(event.time) == 8  # HH:MM:SS

    def test_filter_by_source(self):
        web_state.log_event("sys", "ok", "a")
        web_state.log_event("data", "info", "b")
        assert [e.message for e in web_state.get_log_events("data")] == ["b"]
        assert len(web_state.get_log_events("all")) == 2
        assert len(web_state.get_log_events(None)) == 2

    def test_clear(self):
        web_state.log_event("sys", "ok", "a")
        web_state.clear_log_events()
        assert web_state.get_log_events() == []

    def test_buffer_is_bounded(self):
        for i in range(web_state.LOG_BUFFER_MAX + 100):
            web_state.log_event("sys", "info", str(i))
        events = web_state.get_log_events()
        assert len(events) == web_state.LOG_BUFFER_MAX
        assert events[-1].message == str(web_state.LOG_BUFFER_MAX + 99)


class TestSnapshots:
    def test_unset_returns_none(self):
        assert web_state.get_last_synced("datasets") is None

    def test_mark_and_read_last_synced(self):
        web_state.mark_synced("datasets")
        stamp = web_state.get_last_synced("datasets")
        assert isinstance(stamp, str)
        assert len(stamp) == 8
