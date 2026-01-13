"""Command-line interface for Cryptrink trading agent."""

from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from cryptrink import __version__
from cryptrink.core.config import ExecutionMode, load_config
from cryptrink.core.logging import setup_logging

app = typer.Typer(
    name="cryptrink",
    help="Crypto trading agent for Revolut X with backtesting and strategy support.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold blue]cryptrink[/bold blue] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Cryptrink - Crypto trading agent for Revolut X."""
    pass


@app.command()
def run(
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    mode: Annotated[
        ExecutionMode,
        typer.Option("--mode", "-m", help="Execution mode."),
    ] = ExecutionMode.PAPER,
    strategy: Annotated[
        str | None,
        typer.Option("--strategy", "-s", help="Strategy to run."),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Trading symbol (e.g., BTC-EUR)."),
    ] = None,
) -> None:
    """Run the trading agent."""
    setup_logging()
    config = load_config(config_path)

    console.print(
        Panel(
            f"[bold green]Starting Cryptrink[/bold green]\n\n"
            f"Mode: {mode.value}\n"
            f"Strategy: {strategy or config.default_strategy}\n"
            f"Symbol: {symbol or 'All configured symbols'}",
            title="Cryptrink Trading Agent",
            border_style="blue",
        )
    )

    # TODO: Implement trading engine startup
    console.print("[yellow]Trading engine not yet implemented.[/yellow]")


@app.command()
def backtest(
    strategy: Annotated[str, typer.Argument(help="Strategy to backtest.")],
    symbol: Annotated[str, typer.Argument(help="Trading symbol (e.g., BTC-EUR).")],
    start_date: Annotated[
        str,
        typer.Option("--start", "-s", help="Start date (YYYY-MM-DD)."),
    ] = "2024-01-01",
    end_date: Annotated[
        str | None,
        typer.Option("--end", "-e", help="End date (YYYY-MM-DD)."),
    ] = None,
    initial_capital: Annotated[
        float,
        typer.Option("--capital", help="Initial capital in EUR."),
    ] = 10000.0,
) -> None:
    """Run a backtest for a strategy."""
    setup_logging()

    console.print(
        Panel(
            f"[bold cyan]Backtesting[/bold cyan]\n\n"
            f"Strategy: {strategy}\n"
            f"Symbol: {symbol}\n"
            f"Period: {start_date} to {end_date or 'now'}\n"
            f"Initial Capital: €{initial_capital:,.2f}",
            title="Backtest Configuration",
            border_style="cyan",
        )
    )

    # TODO: Implement backtesting engine
    console.print("[yellow]Backtesting engine not yet implemented.[/yellow]")


@app.command()
def suggest(
    strategy: Annotated[str, typer.Argument(help="Strategy to use for suggestions.")],
    symbol: Annotated[str, typer.Argument(help="Trading symbol (e.g., BTC-EUR).")],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (table, json)."),
    ] = "table",
) -> None:
    """Get trade suggestions without executing."""
    setup_logging()

    console.print(
        Panel(
            f"[bold magenta]Trade Suggestions[/bold magenta]\n\n"
            f"Strategy: {strategy}\n"
            f"Symbol: {symbol}\n"
            f"Format: {output_format}",
            title="Suggestion Mode",
            border_style="magenta",
        )
    )

    # TODO: Implement suggestion generation
    console.print("[yellow]Suggestion engine not yet implemented.[/yellow]")


@app.command()
def status() -> None:
    """Show current trading status and positions."""
    console.print(
        Panel(
            "[bold]Trading Status[/bold]\n\nNo active trading session.",
            title="Status",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
