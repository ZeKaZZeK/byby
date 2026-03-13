"""Main CLI entry point."""
from __future__ import annotations

import asyncio

import click

from byby.logging_config import configure_logging


@click.group()
@click.version_option(version="0.1.0", prog_name="byby")
def main():
    """Byby - Adaptive trading bot for Bybit."""
    pass


@main.command()
@click.option("--symbol", default=None, help="Trading symbol (overrides env)")
@click.option("--testnet/--no-testnet", default=True, help="Use testnet")
def paper(symbol, testnet):
    """Run paper trading on Bybit testnet."""
    configure_logging()
    from byby.paper_trade.runner import run_paper_trading
    asyncio.run(run_paper_trading())


@main.command()
@click.option("--symbol", default="BTC/USDT:USDT")
@click.option("--start", default=None)
@click.option("--end", default=None)
@click.option("--capital", default=10000.0)
@click.option("--output", default="reports")
@click.option("--data-file", default=None)
def backtest(symbol, start, end, capital, output, data_file):
    """Run backtest."""
    from byby.backtest.runner import main as backtest_cmd
    backtest_cmd.main(
        standalone_mode=False,
        args=[
            "--symbol", symbol,
            *(["--start", start] if start else []),
            *(["--end", end] if end else []),
            "--capital", str(capital),
            "--output", output,
            *(["--data-file", data_file] if data_file else []),
        ],
    )


@main.command()
def info():
    """Show configuration and status."""
    from byby.config import get_settings
    settings = get_settings()
    click.echo(f"Symbol: {settings.trading_symbol}")
    click.echo(f"Testnet: {settings.bybit_testnet}")
    click.echo(f"Max risk per trade: {settings.max_risk_per_trade:.1%}")
    click.echo(f"Max daily loss: {settings.max_daily_loss:.1%}")
    click.echo(f"Paper trading: {settings.paper_trading}")


if __name__ == "__main__":
    main()
