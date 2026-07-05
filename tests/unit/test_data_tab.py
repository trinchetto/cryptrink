"""Tests for the Data tab's terminal log + handler outputs.

The Data tab writes every action to a single shared terminal log
(``_LOG``); each handler returns the rendered code-block instead of
populating a separate status component. The tests below assert each
handler's contribution — both the log lines that get appended and the
explicit Started / Completed markers around long DB ops.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.data.storage import OHLCVRepository
from cryptrink.runtime import build_session_factory
from cryptrink.web import state as web_state
from cryptrink.web.state import WebRuntime, reset_runtime

if TYPE_CHECKING:
    from pathlib import Path

gr = pytest.importorskip("gradio")  # data tab imports gradio at module load

from cryptrink.web.tabs import data as data_tab  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate() -> None:
    """Reset runtime + log between tests so cases don't bleed state."""
    reset_runtime()
    data_tab._LOG.clear()
    yield
    reset_runtime()
    data_tab._LOG.clear()


def _settings(
    *,
    api_key: str = "",
    private_key: str = "",
    db_url: str = "sqlite+aiosqlite:///:memory:",
) -> Settings:
    return Settings(
        revolutx=RevolutXSettings(
            api_key=SecretStr(api_key),
            private_key=SecretStr(private_key),
        ),
        risk=RiskSettings(),
        database=DatabaseSettings(url=db_url),
        notifications=NotificationSettings(),
    )


def _install_runtime(settings: Settings) -> WebRuntime:
    session_factory = build_session_factory(settings.database.url)
    runtime = WebRuntime(settings=settings, session_factory=session_factory)
    web_state._runtime = runtime
    return runtime


# ----------------------------------------------------------------------
# Terminal helpers
# ----------------------------------------------------------------------


class TestTerminalRendering:
    def test_empty_terminal_shows_placeholder(self) -> None:
        assert "empty terminal" in data_tab._render_terminal()

    def test_emit_appends_and_returns_code_block(self) -> None:
        out = data_tab._emit("hello")
        assert "hello" in out
        assert out.startswith("```")
        assert out.endswith("```")
        assert data_tab._LOG[-1].endswith("hello")

    def test_emit_caps_log_at_max_lines(self) -> None:
        for i in range(data_tab._LOG_MAX_LINES + 50):
            data_tab._emit(f"line {i}")
        assert len(data_tab._LOG) == data_tab._LOG_MAX_LINES
        # Oldest lines were dropped; latest are kept.
        assert "line 49" not in "\n".join(data_tab._LOG)
        assert "line 249" in "\n".join(data_tab._LOG)


class TestFormatDbSize:
    def test_in_memory_db(self) -> None:
        result = data_tab._format_db_size("sqlite+aiosqlite:///:memory:")
        assert "in-memory" in result

    def test_non_sqlite_url(self) -> None:
        result = data_tab._format_db_size("postgresql+asyncpg://user@host/db")
        assert "not a sqlite file" in result

    def test_missing_file(self, tmp_path: Path) -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'never_created.db'}"
        result = data_tab._format_db_size(url)
        assert "does not exist" in result

    def test_existing_file_reports_size(self, tmp_path: Path) -> None:
        path = tmp_path / "existing.db"
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 12345))
        url = f"sqlite+aiosqlite:///{path}"
        result = data_tab._format_db_size(url)
        assert str(path) in result
        assert "MB" in result
        assert "2.0" in result


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------


class TestResetDatabase:
    @pytest.mark.asyncio
    async def test_removes_sqlite_file_and_recreates_schema(self, tmp_path: Path) -> None:
        """Reset must delete the .db file (and any sidecar journal/wal
        files) and re-initialise an empty schema so the runtime is
        usable again immediately after a corruption-recovery click."""
        db_path = tmp_path / "cryptrink.db"
        _install_runtime(_settings(db_url=f"sqlite+aiosqlite:///{db_path}"))

        # Touch the database so the file actually exists before reset.
        from cryptrink.cli.utils import init_db_schema

        runtime = web_state.get_runtime()
        await init_db_schema(runtime.session_factory)
        assert db_path.exists()

        # Drop a fake sidecar AFTER schema init (sqlite's own init
        # would otherwise sweep this away during recovery).
        journal_path = tmp_path / "cryptrink.db-journal"
        journal_path.write_bytes(b"leftover journal")

        # The original file size is captured before reset so we can
        # assert reset truly replaced it (the post-reset file is small
        # because it only holds the empty schema).
        old_size = db_path.stat().st_size
        # Pad with a marker so the post-reset file isn't accidentally
        # the same size as the freshly-init'd schema.
        with db_path.open("ab") as f:
            f.write(b"x" * 50_000)
        post_pad_size = db_path.stat().st_size

        out = await data_tab.reset_database()

        # Leftover journal sidecar was removed.
        assert not journal_path.exists()
        # Main file is back (schema re-init creates it) but is the
        # fresh small schema, not the padded pre-reset blob.
        assert db_path.exists()
        assert db_path.stat().st_size < post_pad_size
        # Required log markers.
        assert "reset: starting" in out
        assert "engine disposed" in out
        assert "removed" in out
        assert "reset: COMPLETE" in out
        # Sanity-check `old_size` was used (silences ARG warnings).
        assert old_size > 0

        # Subsequent reads work — schema has been re-created.
        runtime = web_state.get_runtime()
        from sqlalchemy import text

        async with runtime.session_factory() as session:
            await session.execute(text("SELECT 1"))

    @pytest.mark.asyncio
    async def test_logs_failure_for_non_sqlite_backend(self) -> None:
        # Install with a benign sqlite URL so the runtime builds, then
        # mutate the URL to a non-sqlite one before calling reset —
        # build_session_factory eagerly imports the dialect's DBAPI, so
        # we can't actually instantiate a postgres engine in CI.
        runtime = _install_runtime(_settings())
        runtime.settings.database.url = "postgresql+asyncpg://user:pass@localhost/db"

        out = await data_tab.reset_database()
        assert "FAILED" in out
        assert "not a sqlite file" in out


class TestWipe:
    @pytest.mark.asyncio
    async def test_empty_symbol_logs_failure(self) -> None:
        """Browser confirmation dialog gates user intent now; the
        Python handler still validates that a symbol was provided
        because gr.Dropdown can technically pass an empty string."""
        _install_runtime(_settings())
        out = await data_tab.wipe("", "1h")
        assert "FAILED" in out
        assert "symbol is empty" in out

    @pytest.mark.asyncio
    async def test_zero_rows_warns_about_timeframe_mismatch(self) -> None:
        """If the operator clicks Wipe with a (symbol, timeframe)
        combination that has no rows (typically because they left the
        timeframe dropdown at its default), the log must surface the
        mismatch loudly — silent "deleted 0 rows" caused real
        confusion in production."""
        _install_runtime(_settings())
        out = await data_tab.wipe("BTC-EUR", "1h")
        assert "NO ROWS matched BTC-EUR 1h" in out
        assert "Nothing was deleted" in out
        assert "timeframe dropdown" in out

    @pytest.mark.asyncio
    async def test_logs_started_and_completed_with_count(self) -> None:
        runtime = _install_runtime(_settings())
        repo = OHLCVRepository(runtime.session_factory)
        from cryptrink.cli.utils import init_db_schema

        await init_db_schema(runtime.session_factory)
        await repo.save_batch(
            [
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": 1_700_000_000_000 + i * 3_600_000,
                    "open": Decimal("100"),
                    "high": Decimal("110"),
                    "low": Decimal("90"),
                    "close": Decimal("105"),
                    "volume": Decimal("1"),
                }
                for i in range(2)
            ]
        )

        out = await data_tab.wipe("BTC-EUR", "1h")
        assert "wipe: starting" in out
        assert "wipe: COMPLETE" in out
        assert "deleted 2 rows" in out


class TestRefreshSymbols:
    @pytest.mark.asyncio
    async def test_no_creds_logs_failure(self) -> None:
        _install_runtime(_settings())
        update, log = await data_tab.refresh_symbols("BTC-EUR")
        assert "FAILED" in log
        assert "credentials not configured" in log
        # Dropdown left untouched on failure.
        assert getattr(update, "value", None) is None or update == gr.update()

    @pytest.mark.asyncio
    async def test_loads_symbols_logs_completed(self) -> None:
        runtime = _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
        )

        live_symbols = ["BTC-EUR", "ETH-EUR", "SOL-EUR"]
        with (
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.connect",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.close",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.get_symbols",
                new=AsyncMock(return_value=live_symbols),
            ),
        ):
            update, log = await data_tab.refresh_symbols("BTC-EUR")

        assert update["choices"] == sorted(live_symbols)
        assert update["value"] == "BTC-EUR"
        assert "symbols: COMPLETE" in log
        assert runtime.cached_symbols == sorted(live_symbols)


class TestBackfillStream:
    @pytest.mark.asyncio
    async def test_logs_failure_when_creds_missing(self) -> None:
        _install_runtime(_settings())  # no creds
        outputs: list[str] = []
        async for chunk in data_tab.backfill("BTC-EUR", "1h", "2024-01-01", ""):
            outputs.append(chunk)
        # The stream still emits validation lines; the last yielded chunk
        # must surface the failure to the operator.
        joined = "\n".join(outputs)
        assert "backfill: validating inputs" in joined
        assert "FAILED" in joined
        assert "credentials not configured" in joined

    @pytest.mark.asyncio
    async def test_logs_failure_for_unsupported_timeframe(self) -> None:
        _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
        )
        outputs: list[str] = []
        async for chunk in data_tab.backfill("BTC-EUR", "3m", "2024-01-01", "2024-02-01"):
            outputs.append(chunk)
        joined = "\n".join(outputs)
        assert "FAILED" in joined
        assert "not supported" in joined

    @pytest.mark.asyncio
    async def test_logs_horizon_message_when_api_has_no_older_data(self) -> None:
        """When iter_candle_pages exhausts before reaching `since_ms`,
        the terminal must explain it as the API's data horizon — not a
        cryptrink stop-short. Operator-reported diagnostic gap."""
        _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
        )

        # The "API" returns one page that ends well after `since_ms`,
        # then runs out. iter_candle_pages's empty-page exit fires.
        page = [
            {
                "timestamp": 1_700_000_000_000 + i * 60_000,
                "symbol": "BTC-EUR",
                "timeframe": "1m",
                "open": Decimal("100"),
                "high": Decimal("110"),
                "low": Decimal("90"),
                "close": Decimal("105"),
                "volume": Decimal("1"),
            }
            for i in range(50)
        ]

        async def fake_iter(_self: object, **_kwargs: object) -> object:
            yield page

        with (
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.connect",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.close",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.iter_candle_pages",
                new=fake_iter,
            ),
        ):
            outputs: list[str] = []
            # Request goes way back before anything in `page` — forces
            # the horizon-stop branch.
            async for chunk in data_tab.backfill("BTC-EUR", "1m", "2020-01-01", "2024-01-01"):
                outputs.append(chunk)

        joined = "\n".join(outputs)
        assert "stopped because Revolut X has no data older than" in joined
        assert "use a coarser timeframe (1h, 4h, 1d)" in joined

    @pytest.mark.asyncio
    async def test_logs_reached_start_when_pages_cover_requested_range(self) -> None:
        """When the earliest page reaches at or before since_ms, the
        terminal must report 'requested start was reached', not the
        retention-horizon message."""
        _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
        )

        # Single page whose earliest is well before the requested start.
        page = [
            {
                "timestamp": 1_700_000_000_000 + i * 60_000,
                "symbol": "BTC-EUR",
                "timeframe": "1m",
                "open": Decimal("100"),
                "high": Decimal("110"),
                "low": Decimal("90"),
                "close": Decimal("105"),
                "volume": Decimal("1"),
            }
            for i in range(10)
        ]

        async def fake_iter(_self: object, **_kwargs: object) -> object:
            yield page

        with (
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.connect",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.close",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.iter_candle_pages",
                new=fake_iter,
            ),
        ):
            outputs: list[str] = []
            # Request starts AFTER the earliest candle in the page.
            async for chunk in data_tab.backfill("BTC-EUR", "1m", "2024-01-01", "2024-12-31"):
                outputs.append(chunk)

        joined = "\n".join(outputs)
        assert "stopped because requested start was reached" in joined
        assert "no data older than" not in joined
