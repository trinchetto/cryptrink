"""Performance metrics calculation for backtesting.

This module calculates comprehensive performance metrics for backtest results,
including returns, risk-adjusted metrics, trade statistics, and drawdown analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.models import Order, Position


class TradeStatsDict(TypedDict):
    """Type definition for trade statistics dictionary."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    profit_factor: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    avg_trade: Decimal
    best_trade: Decimal
    worst_trade: Decimal
    max_win_streak: int
    max_loss_streak: int
    current_streak: int


class StreakStatsDict(TypedDict):
    """Type definition for streak statistics dictionary."""

    max_win_streak: int
    max_loss_streak: int
    current_streak: int


logger = get_logger(__name__)


@dataclass
class BacktestMetrics:
    """Comprehensive performance metrics for a backtest.

    This dataclass contains all calculated metrics including returns,
    risk-adjusted metrics, trade statistics, and drawdown analysis.
    """

    # Returns
    total_return: Decimal  # Total dollar return
    total_return_pct: Decimal  # Total percentage return
    annualized_return: Decimal  # Annualized return percentage

    # Risk Metrics
    sharpe_ratio: Decimal  # Risk-adjusted return (Sharpe)
    sortino_ratio: Decimal  # Downside risk-adjusted return
    max_drawdown: Decimal  # Maximum drawdown percentage
    max_drawdown_duration: int  # Days in maximum drawdown

    # Trade Statistics
    total_trades: int  # Total number of closed trades
    winning_trades: int  # Number of winning trades
    losing_trades: int  # Number of losing trades
    win_rate: Decimal  # Win rate percentage (0-1)
    profit_factor: Decimal  # Gross profit / gross loss
    avg_win: Decimal  # Average winning trade
    avg_loss: Decimal  # Average losing trade (positive value)
    avg_trade: Decimal  # Average trade P&L
    best_trade: Decimal  # Best trade P&L
    worst_trade: Decimal  # Worst trade P&L

    # Win/Loss Streaks
    max_win_streak: int  # Maximum consecutive wins
    max_loss_streak: int  # Maximum consecutive losses
    current_streak: int  # Current streak (positive = wins, negative = losses)

    # Time-based
    total_days: int  # Total days in backtest
    trading_days: int  # Days with open position

    # Equity
    starting_equity: Decimal  # Starting balance
    ending_equity: Decimal  # Ending balance
    peak_equity: Decimal  # Peak equity reached


class BacktestMetricsCalculator:
    """Calculate comprehensive performance metrics from backtest results.

    This calculator processes closed positions, orders, and equity curve
    to generate detailed performance statistics.
    """

    def __init__(self, risk_free_rate: Decimal = Decimal("0.02")) -> None:
        """Initialize metrics calculator.

        Args:
            risk_free_rate: Annual risk-free rate for Sharpe/Sortino calculation.
                Default 0.02 (2% annual).
        """
        self._risk_free_rate = risk_free_rate

        logger.info(
            "backtest_metrics_calculator_initialized",
            risk_free_rate=float(risk_free_rate),
        )

    def calculate(
        self,
        positions: list[Position],
        orders: list[Order],
        initial_balance: Decimal,
        final_balance: Decimal,
        start_time: datetime,
        end_time: datetime,
        equity_curve: list[tuple[datetime, Decimal]],
    ) -> BacktestMetrics:
        """Calculate all backtest metrics.

        Args:
            positions: List of closed positions.
            orders: List of all orders.
            initial_balance: Starting balance.
            final_balance: Ending balance.
            start_time: Backtest start time.
            end_time: Backtest end time.
            equity_curve: List of (timestamp, equity) tuples.

        Returns:
            BacktestMetrics with all calculated metrics.
        """
        logger.info(
            "calculating_backtest_metrics",
            num_positions=len(positions),
            num_orders=len(orders),
            initial_balance=float(initial_balance),
            final_balance=float(final_balance),
        )

        # Calculate returns
        total_return = final_balance - initial_balance
        total_return_pct = total_return / initial_balance if initial_balance > 0 else Decimal("0")

        # Calculate annualized return
        total_days = (end_time - start_time).days
        years = Decimal(str(total_days / 365.25)) if total_days > 0 else Decimal("1")
        annualized_return = self._calculate_annualized_return(total_return_pct, years)

        # Calculate risk-adjusted metrics
        daily_returns = self._calculate_daily_returns(equity_curve)
        sharpe_ratio = self._calculate_sharpe_ratio(daily_returns, years)
        sortino_ratio = self._calculate_sortino_ratio(daily_returns, years)

        # Calculate drawdown metrics
        max_drawdown, max_drawdown_duration = self._calculate_drawdown_metrics(equity_curve)

        # Calculate trade statistics
        trade_stats = self._calculate_trade_stats(positions)

        # Calculate trading days
        trading_days = self._calculate_trading_days(positions)

        # Find peak equity
        peak_equity = max((eq for _, eq in equity_curve), default=initial_balance)

        metrics = BacktestMetrics(
            # Returns
            total_return=total_return,
            total_return_pct=total_return_pct,
            annualized_return=annualized_return,
            # Risk Metrics
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_drawdown_duration,
            # Trade Statistics
            total_trades=trade_stats["total_trades"],
            winning_trades=trade_stats["winning_trades"],
            losing_trades=trade_stats["losing_trades"],
            win_rate=trade_stats["win_rate"],
            profit_factor=trade_stats["profit_factor"],
            avg_win=trade_stats["avg_win"],
            avg_loss=trade_stats["avg_loss"],
            avg_trade=trade_stats["avg_trade"],
            best_trade=trade_stats["best_trade"],
            worst_trade=trade_stats["worst_trade"],
            # Streaks
            max_win_streak=trade_stats["max_win_streak"],
            max_loss_streak=trade_stats["max_loss_streak"],
            current_streak=trade_stats["current_streak"],
            # Time-based
            total_days=total_days,
            trading_days=trading_days,
            # Equity
            starting_equity=initial_balance,
            ending_equity=final_balance,
            peak_equity=peak_equity,
        )

        logger.info(
            "backtest_metrics_calculated",
            total_return_pct=float(total_return_pct * 100),
            sharpe_ratio=float(sharpe_ratio),
            max_drawdown=float(max_drawdown * 100),
            win_rate=float(trade_stats["win_rate"] * 100),
            total_trades=trade_stats["total_trades"],
        )

        return metrics

    def _calculate_annualized_return(self, total_return_pct: Decimal, years: Decimal) -> Decimal:
        """Calculate annualized return.

        Formula: (1 + total_return) ^ (1 / years) - 1

        Args:
            total_return_pct: Total return percentage.
            years: Number of years.

        Returns:
            Annualized return percentage.
        """
        if years <= 0:
            return Decimal("0")

        # Convert to float for power calculation
        compound = float(1 + total_return_pct)
        exponent = 1.0 / float(years)
        annualized = Decimal(str(compound**exponent - 1))

        return annualized

    def _calculate_daily_returns(
        self, equity_curve: list[tuple[datetime, Decimal]]
    ) -> list[Decimal]:
        """Calculate daily returns from equity curve.

        Args:
            equity_curve: List of (timestamp, equity) tuples.

        Returns:
            List of daily return percentages.
        """
        if len(equity_curve) < 2:
            return []

        daily_returns: list[Decimal] = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i - 1][1]
            curr_equity = equity_curve[i][1]

            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                daily_returns.append(daily_return)

        return daily_returns

    def _calculate_sharpe_ratio(self, daily_returns: list[Decimal], years: Decimal) -> Decimal:
        """Calculate Sharpe ratio.

        Formula: (mean_return - risk_free_rate) / std_dev
        Annualized using sqrt(trading days per year)

        Args:
            daily_returns: List of daily return percentages.
            years: Number of years (for annualization).

        Returns:
            Sharpe ratio.
        """
        if len(daily_returns) < 2:
            return Decimal("0")

        # Calculate mean and standard deviation
        mean_return = sum(daily_returns, Decimal("0")) / Decimal(str(len(daily_returns)))
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / Decimal(
            str(len(daily_returns) - 1)
        )
        std_dev = Decimal(str(float(variance) ** 0.5))

        if std_dev == 0:
            return Decimal("0")

        # Daily risk-free rate
        daily_rf = self._risk_free_rate / Decimal("252")  # Assume 252 trading days per year

        # Calculate Sharpe ratio
        sharpe = (mean_return - daily_rf) / std_dev

        # Annualize (sqrt of trading days per year)
        annualization_factor = Decimal(str(252**0.5))
        sharpe_annualized = sharpe * annualization_factor

        return sharpe_annualized

    def _calculate_sortino_ratio(self, daily_returns: list[Decimal], years: Decimal) -> Decimal:
        """Calculate Sortino ratio (downside deviation only).

        Formula: mean_return / downside_deviation

        Args:
            daily_returns: List of daily return percentages.
            years: Number of years (for annualization).

        Returns:
            Sortino ratio.
        """
        if len(daily_returns) < 2:
            return Decimal("0")

        # Calculate mean return
        mean_return = sum(daily_returns, Decimal("0")) / Decimal(str(len(daily_returns)))

        # Calculate downside deviation (only negative returns)
        negative_returns = [r for r in daily_returns if r < 0]
        if not negative_returns:
            # No losses, infinite Sortino (return very high number)
            return Decimal("999")

        downside_variance = sum((r**2 for r in negative_returns), Decimal("0")) / Decimal(
            str(len(negative_returns))
        )
        downside_dev = Decimal(str(float(downside_variance) ** 0.5))

        if downside_dev == 0:
            return Decimal("0")

        # Calculate Sortino ratio
        sortino = mean_return / downside_dev

        # Annualize
        annualization_factor = Decimal(str(252**0.5))
        sortino_annualized = sortino * annualization_factor

        return sortino_annualized

    def _calculate_drawdown_metrics(
        self, equity_curve: list[tuple[datetime, Decimal]]
    ) -> tuple[Decimal, int]:
        """Calculate maximum drawdown and duration.

        Args:
            equity_curve: List of (timestamp, equity) tuples.

        Returns:
            Tuple of (max_drawdown percentage, max_drawdown_duration in days).
        """
        if len(equity_curve) < 2:
            return Decimal("0"), 0

        max_drawdown = Decimal("0")
        max_drawdown_duration = 0
        peak_equity = equity_curve[0][1]
        peak_time = equity_curve[0][0]

        for timestamp, equity in equity_curve:
            # Update peak
            if equity > peak_equity:
                peak_equity = equity
                peak_time = timestamp
            else:
                # Calculate drawdown
                drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else Decimal("0")
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

                # Calculate duration
                duration = (timestamp - peak_time).days
                if duration > max_drawdown_duration:
                    max_drawdown_duration = duration

        return max_drawdown, max_drawdown_duration

    def _calculate_trade_stats(self, positions: list[Position]) -> TradeStatsDict:
        """Calculate trade statistics from closed positions.

        Args:
            positions: List of closed positions.

        Returns:
            Dictionary with trade statistics.
        """
        if not positions:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": Decimal("0"),
                "profit_factor": Decimal("0"),
                "avg_win": Decimal("0"),
                "avg_loss": Decimal("0"),
                "avg_trade": Decimal("0"),
                "best_trade": Decimal("0"),
                "worst_trade": Decimal("0"),
                "max_win_streak": 0,
                "max_loss_streak": 0,
                "current_streak": 0,
            }

        # Extract P&L from positions
        pnls = [Decimal(str(pos.realized_pnl)) for pos in positions]

        # Separate wins and losses
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]

        # Calculate basic stats
        total_trades = len(positions)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = Decimal(str(winning_trades / total_trades)) if total_trades > 0 else Decimal("0")

        # Calculate profit factor
        gross_profit = sum(wins, Decimal("0")) if wins else Decimal("0")
        gross_loss = abs(sum(losses, Decimal("0"))) if losses else Decimal("0")
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal("0")

        # Calculate averages
        avg_win = sum(wins, Decimal("0")) / Decimal(str(len(wins))) if wins else Decimal("0")
        avg_loss = (
            abs(sum(losses, Decimal("0")) / Decimal(str(len(losses)))) if losses else Decimal("0")
        )
        avg_trade = sum(pnls, Decimal("0")) / Decimal(str(len(pnls))) if pnls else Decimal("0")

        # Best and worst
        best_trade = max(pnls) if pnls else Decimal("0")
        worst_trade = min(pnls) if pnls else Decimal("0")

        # Calculate streaks
        streaks = self._calculate_streaks(pnls)

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_trade": avg_trade,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "max_win_streak": streaks["max_win_streak"],
            "max_loss_streak": streaks["max_loss_streak"],
            "current_streak": streaks["current_streak"],
        }

    def _calculate_streaks(self, pnls: list[Decimal]) -> StreakStatsDict:
        """Calculate win/loss streaks.

        Args:
            pnls: List of trade P&Ls.

        Returns:
            Dictionary with streak information.
        """
        if not pnls:
            return {"max_win_streak": 0, "max_loss_streak": 0, "current_streak": 0}

        max_win_streak = 0
        max_loss_streak = 0
        current_streak = 0

        for pnl in pnls:
            if pnl > 0:
                # Win
                if current_streak >= 0:
                    current_streak += 1
                else:
                    current_streak = 1
                max_win_streak = max(max_win_streak, current_streak)
            elif pnl < 0:
                # Loss
                if current_streak <= 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))

        return {
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "current_streak": current_streak,
        }

    def _calculate_trading_days(self, positions: list[Position]) -> int:
        """Calculate number of days with open positions.

        Args:
            positions: List of closed positions.

        Returns:
            Number of trading days.
        """
        if not positions:
            return 0

        # Get unique days when positions were open
        trading_dates = set()
        for pos in positions:
            if pos.opened_at and pos.closed_at:
                # Convert millisecond timestamps to datetime
                open_time = datetime.fromtimestamp(pos.opened_at / 1000)
                close_time = datetime.fromtimestamp(pos.closed_at / 1000)

                # Add all days between open and close
                current_date = open_time.date()
                end_date = close_time.date()
                while current_date <= end_date:
                    trading_dates.add(current_date)
                    current_date += timedelta(days=1)

        return len(trading_dates)
