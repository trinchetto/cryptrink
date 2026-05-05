"""Backtest result dataclass with visualization and persistence.

This module defines the BacktestResult dataclass that encapsulates all
backtest results including metrics, equity curve, trade history, and
provides methods for visualization and persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal  # noqa: TC003
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.backtest.metrics import BacktestMetrics
    from cryptrink.execution.models import Order, Position

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Comprehensive backtest result with metrics and trade history.

    This dataclass contains all information about a completed backtest,
    including performance metrics, equity curve, trade history, and
    drawdown analysis.
    """

    # Configuration
    strategy_name: str
    symbol: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    initial_balance: Decimal

    # Performance Metrics
    metrics: BacktestMetrics

    # Equity Curve
    equity_curve: list[tuple[datetime, Decimal]]

    # Trade History
    trades: list[Position]  # Closed positions
    orders: list[Order]  # All orders

    # Risk Metrics Over Time
    drawdown_curve: list[tuple[datetime, Decimal]]

    def to_dict(self) -> dict[str, object]:
        """Serialize backtest result to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "initial_balance": str(self.initial_balance),
            "metrics": {
                "total_return": str(self.metrics.total_return),
                "total_return_pct": str(self.metrics.total_return_pct),
                "annualized_return": str(self.metrics.annualized_return),
                "sharpe_ratio": str(self.metrics.sharpe_ratio),
                "sortino_ratio": str(self.metrics.sortino_ratio),
                "max_drawdown": str(self.metrics.max_drawdown),
                "max_drawdown_duration": self.metrics.max_drawdown_duration,
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "win_rate": str(self.metrics.win_rate),
                "profit_factor": str(self.metrics.profit_factor),
                "avg_win": str(self.metrics.avg_win),
                "avg_loss": str(self.metrics.avg_loss),
                "avg_trade": str(self.metrics.avg_trade),
                "best_trade": str(self.metrics.best_trade),
                "worst_trade": str(self.metrics.worst_trade),
                "max_win_streak": self.metrics.max_win_streak,
                "max_loss_streak": self.metrics.max_loss_streak,
                "current_streak": self.metrics.current_streak,
                "total_days": self.metrics.total_days,
                "trading_days": self.metrics.trading_days,
                "starting_equity": str(self.metrics.starting_equity),
                "ending_equity": str(self.metrics.ending_equity),
                "peak_equity": str(self.metrics.peak_equity),
            },
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": str(eq)} for ts, eq in self.equity_curve
            ],
            "drawdown_curve": [
                {"timestamp": ts.isoformat(), "drawdown": str(dd)} for ts, dd in self.drawdown_curve
            ],
            "total_orders": len(self.orders),
            "total_positions": len(self.trades),
        }

    def print_summary(self) -> None:
        """Print human-readable summary of backtest results."""
        print("\n" + "=" * 70)
        print(f"Backtest Results: {self.strategy_name} on {self.symbol}")
        print("=" * 70)
        print(f"Period: {self.start_time.date()} to {self.end_time.date()}")
        print(f"Timeframe: {self.timeframe}")
        print(f"Total Days: {self.metrics.total_days}")
        print(f"Trading Days: {self.metrics.trading_days}")
        print()

        print("RETURNS")
        print("-" * 70)
        print(f"Initial Balance:     ${self.initial_balance:>12,.2f}")
        print(f"Final Balance:       ${self.metrics.ending_equity:>12,.2f}")
        print(f"Total Return:        ${self.metrics.total_return:>12,.2f}")
        print(f"Total Return %:      {self.metrics.total_return_pct * 100:>12.2f}%")
        print(f"Annualized Return:   {self.metrics.annualized_return * 100:>12.2f}%")
        print()

        print("RISK METRICS")
        print("-" * 70)
        print(f"Sharpe Ratio:        {self.metrics.sharpe_ratio:>12.2f}")
        print(f"Sortino Ratio:       {self.metrics.sortino_ratio:>12.2f}")
        print(f"Max Drawdown:        {self.metrics.max_drawdown * 100:>12.2f}%")
        print(f"Max DD Duration:     {self.metrics.max_drawdown_duration:>12} days")
        print(f"Peak Equity:         ${self.metrics.peak_equity:>12,.2f}")
        print()

        print("TRADE STATISTICS")
        print("-" * 70)
        print(f"Total Trades:        {self.metrics.total_trades:>12}")
        print(f"Winning Trades:      {self.metrics.winning_trades:>12}")
        print(f"Losing Trades:       {self.metrics.losing_trades:>12}")
        print(f"Win Rate:            {self.metrics.win_rate * 100:>12.1f}%")
        print(f"Profit Factor:       {self.metrics.profit_factor:>12.2f}")
        print()

        print("TRADE AVERAGES")
        print("-" * 70)
        print(f"Average Win:         ${self.metrics.avg_win:>12,.2f}")
        print(f"Average Loss:        ${self.metrics.avg_loss:>12,.2f}")
        print(f"Average Trade:       ${self.metrics.avg_trade:>12,.2f}")
        print(f"Best Trade:          ${self.metrics.best_trade:>12,.2f}")
        print(f"Worst Trade:         ${self.metrics.worst_trade:>12,.2f}")
        print()

        print("WIN/LOSS STREAKS")
        print("-" * 70)
        print(f"Max Win Streak:      {self.metrics.max_win_streak:>12}")
        print(f"Max Loss Streak:     {self.metrics.max_loss_streak:>12}")
        print(f"Current Streak:      {self.metrics.current_streak:>12}")
        print("=" * 70)
        print()

    def plot_equity_curve(
        self,
        show_drawdown: bool = True,
        save_path: str | None = None,
    ) -> None:
        """Plot equity curve with optional drawdown overlay.

        Args:
            show_drawdown: If True, overlay drawdown as shaded area.
            save_path: If provided, save figure to file instead of showing.
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError as e:
            msg = "matplotlib is required for plotting. Install with: pip install matplotlib"
            raise ImportError(msg) from e

        fig, ax1 = plt.subplots(figsize=(12, 6))

        # Extract timestamps and equity values
        timestamps = [ts for ts, _ in self.equity_curve]
        equity = [float(eq) for _, eq in self.equity_curve]

        # Plot equity curve (matplotlib handles datetime objects automatically;
        # the type stubs do not, hence the ignore).
        ax1.plot(timestamps, equity, label="Equity", color="blue", linewidth=2)  # type: ignore[arg-type]
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Equity ($)", color="blue")
        ax1.tick_params(axis="y", labelcolor="blue")
        ax1.grid(True, alpha=0.3)

        # Add horizontal line for initial balance
        ax1.axhline(
            y=float(self.initial_balance),
            color="gray",
            linestyle="--",
            alpha=0.5,
            label="Initial Balance",
        )

        # Add drawdown overlay if requested
        if show_drawdown and self.drawdown_curve:
            ax2 = ax1.twinx()
            dd_timestamps = [ts for ts, _ in self.drawdown_curve]
            dd_values = [float(dd) * -100 for _, dd in self.drawdown_curve]  # As negative %
            # Matplotlib fill_between handles datetime objects (type stubs are incomplete)
            ax2.fill_between(
                dd_timestamps,  # type: ignore[arg-type]
                dd_values,
                0,
                alpha=0.3,
                color="red",
                label="Drawdown",
            )
            ax2.set_ylabel("Drawdown (%)", color="red")
            ax2.tick_params(axis="y", labelcolor="red")

            # Combine legends from both axes
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        else:
            ax1.legend(loc="upper left")

        # Title with key metrics
        title = f"{self.strategy_name} on {self.symbol} ({self.timeframe})\n"
        title += f"Return: {self.metrics.total_return_pct * 100:.2f}% | "
        title += f"Sharpe: {self.metrics.sharpe_ratio:.2f} | "
        title += f"Max DD: {self.metrics.max_drawdown * 100:.2f}%"
        plt.title(title)

        fig.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            logger.info("equity_curve_saved", path=save_path)
            plt.close()
        else:
            plt.show()

    def plot_trade_distribution(self, save_path: str | None = None) -> None:
        """Plot distribution of trade P&L.

        Args:
            save_path: If provided, save figure to file instead of showing.
        """
        try:
            import matplotlib.pyplot as plt  # type: ignore[import-not-found,unused-ignore]
        except ImportError as e:
            msg = "matplotlib is required for plotting. Install with: pip install matplotlib"
            raise ImportError(msg) from e

        if not self.trades:
            logger.warning("no_trades_to_plot")
            return

        # Extract P&L values
        pnls = [float(pos.realized_pnl) for pos in self.trades]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Histogram
        ax1.hist(pnls, bins=30, alpha=0.7, color="blue", edgecolor="black")
        ax1.axvline(x=0, color="red", linestyle="--", alpha=0.5, label="Break-even")
        ax1.axvline(
            x=float(self.metrics.avg_trade),
            color="green",
            linestyle="--",
            alpha=0.7,
            label="Average Trade",
        )
        ax1.set_xlabel("P&L ($)")
        ax1.set_ylabel("Frequency")
        ax1.set_title("Trade P&L Distribution")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Cumulative P&L over time
        cumulative_pnl: list[float] = []
        running_total = 0.0
        timestamps = []
        for pos in sorted(self.trades, key=lambda p: p.closed_at or 0):
            running_total += float(pos.realized_pnl)
            cumulative_pnl.append(running_total)
            if pos.closed_at:
                timestamps.append(datetime.fromtimestamp(pos.closed_at / 1000))

        ax2.plot(timestamps, cumulative_pnl, linewidth=2, color="green")
        ax2.axhline(y=0, color="red", linestyle="--", alpha=0.5)
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Cumulative P&L ($)")
        ax2.set_title("Cumulative Trade P&L Over Time")
        ax2.grid(True, alpha=0.3)

        fig.suptitle(f"Trade Analysis: {self.strategy_name} on {self.symbol}", fontsize=14)
        fig.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            logger.info("trade_distribution_saved", path=save_path)
            plt.close()
        else:
            plt.show()
