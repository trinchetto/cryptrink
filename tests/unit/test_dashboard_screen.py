"""Tests for the Dashboard screen's pure helpers."""

from __future__ import annotations

import pandas as pd

from cryptrink.web.screens import dashboard


class TestMetricsHtml:
    def test_has_all_labels(self):
        html = dashboard.metrics_html("€0.00", "+€0.00", "+€0.00", "0")
        # "Open P&L" renders HTML-escaped as "Open P&amp;L".
        for label in ("Account equity", "Open P&amp;L", "Realised", "Active engines"):
            assert label in html

    def test_embeds_values(self):
        html = dashboard.metrics_html("€1,234", "+€10", "-€5", "2")
        assert "€1,234" in html
        assert "2" in html


class TestDeriveMetrics:
    def test_empty_frames(self):
        engines = pd.DataFrame(columns=["running", "current_balance"])
        positions = pd.DataFrame(columns=["status", "realized_pnl"])
        m = dashboard.derive_metrics(engines, positions)
        assert m["active_engines"] == "0"
        assert m["account_equity"] == "—"

    def test_counts_running_engines_and_balance(self):
        engines = pd.DataFrame(
            [
                {"running": True, "current_balance": 10000.0},
                {"running": False, "current_balance": 5000.0},
            ]
        )
        positions = pd.DataFrame(
            [
                {"status": "open", "realized_pnl": 0.0},
                {"status": "closed", "realized_pnl": 120.5},
            ]
        )
        m = dashboard.derive_metrics(engines, positions)
        assert m["active_engines"] == "1"
        assert "15,000" in m["account_equity"]
        assert "120" in m["realised"]
