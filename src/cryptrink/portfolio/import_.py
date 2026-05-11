"""Build a :class:`Portfolio` from a live Revolut X account snapshot.

The Portfolio tab calls :func:`build_portfolio_from_balances` to seed
its YAML editor with the operator's real holdings. The function is kept
pure of UI / database concerns so it can be unit-tested with a fake
exchange — it talks only to a :class:`BaseExchange`-shaped object and
produces an :class:`ImportResult`.

Design choices:

* **Quote currency is the fiat with the largest balance.** Revolut
  accounts may hold multiple fiat currencies; we treat the dominant
  one as "cash" and price every crypto holding against it. If the
  operator wants a different quote they can edit the YAML afterward.
* **Holdings are priced via :meth:`get_ticker`.** Using the OHLCV
  store would couple the import to backfill state (which is the
  operator's job to manage *after* importing). Live ticker is the
  authoritative current price and what the operator sees on Revolut.
* **Crypto with no tradeable pair is skipped, not silently dropped.**
  If the operator holds e.g. USDT but USDT-EUR isn't listed on the
  exchange, ``get_ticker`` raises and we record the symbol in
  :attr:`ImportResult.skipped` so the UI can surface it.
* **Weight = quote_value / total_equity.** A first-cut hint; the
  engine doesn't consume weights yet (Phase 1.5) but recording them
  now means the operator's import already reflects portfolio
  composition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.portfolio.models import Allocation, Portfolio

if TYPE_CHECKING:
    from cryptrink.exchange.base import BaseExchange


logger = get_logger(__name__)


# Fiat currencies Revolut X is known to support as a quote side. Any
# balance in one of these is treated as cash; anything else is treated
# as a tradeable crypto asset. We keep the set explicit (rather than
# inferring from pair listings) so the import behaves the same whether
# the operator has historic data backfilled or not.
KNOWN_FIATS: frozenset[str] = frozenset({"EUR", "USD", "GBP", "CHF"})


@dataclass
class ImportResult:
    """Outcome of an import-from-Revolut run."""

    portfolio: Portfolio
    quote_currency: str
    total_equity: Decimal
    warnings: list[str] = field(default_factory=list)
    # Crypto symbols whose ticker fetch failed (e.g. no tradeable pair
    # against the chosen quote). The UI surfaces these so the operator
    # knows why a holding didn't make it into the YAML.
    skipped: list[str] = field(default_factory=list)


async def build_portfolio_from_balances(
    exchange: BaseExchange,
    *,
    name: str = "revolutx_import",
    timeframe: str = "1h",
    strategy_name: str = "rsi_mean_reversion",
) -> ImportResult:
    """Snapshot the exchange account and turn it into a :class:`Portfolio`.

    Args:
        exchange: A connected :class:`BaseExchange` instance. The caller
            is responsible for ``connect()``/``close()`` — keeping this
            function passive means the same code path covers tests and
            production without a context-manager fight.
        name: Filename-safe name for the generated portfolio. Defaults
            to ``"revolutx_import"`` so subsequent imports overwrite the
            same file unless the operator renames it.
        timeframe: Candle timeframe the portfolio engine will run on.
            All allocations share this in Phase 1.
        strategy_name: Strategy that every imported allocation starts
            with. Operator can edit each allocation in the YAML.

    Returns:
        :class:`ImportResult` with the constructed portfolio, the chosen
        quote currency, total equity (priced at the live ticker), plus
        warning / skipped lists for the UI.

    Raises:
        ValueError: If the account has no fiat balance to use as quote,
            or no crypto holdings at all.
    """
    balances = await exchange.get_balances()

    # Partition: fiats become cash candidates, the rest are crypto.
    fiats: dict[str, Decimal] = {}
    crypto: dict[str, Decimal] = {}
    for currency, balance in balances.items():
        total = balance.total
        if total <= 0:
            continue
        if currency in KNOWN_FIATS:
            fiats[currency] = total
        else:
            crypto[currency] = total

    if not fiats:
        raise ValueError(
            "No fiat balance found on the account. Cryptrink picks the dominant fiat "
            "as the quote currency for every imported allocation, so at least one of "
            f"{sorted(KNOWN_FIATS)} must hold a non-zero balance."
        )

    quote = max(fiats, key=lambda c: fiats[c])
    fiat_balance = fiats[quote]

    if not crypto:
        raise ValueError(
            f"Account holds {fiat_balance} {quote} in cash but no crypto. There is "
            "nothing to allocate — fund the account with at least one crypto asset "
            "or define the portfolio manually."
        )

    # Price every crypto holding against the chosen quote.
    allocations: list[Allocation] = []
    skipped: list[str] = []
    warnings: list[str] = []
    holdings_value = Decimal("0")
    holding_quote_values: dict[str, Decimal] = {}

    for coin, qty in sorted(crypto.items()):
        symbol = f"{coin}-{quote}"
        try:
            ticker = await exchange.get_ticker(symbol)
        except Exception as exc:
            logger.warning(
                "portfolio_import_ticker_failed",
                symbol=symbol,
                error=f"{type(exc).__name__}: {exc}",
            )
            skipped.append(coin)
            warnings.append(
                f"Skipped {coin}: no tradeable pair {symbol} ({type(exc).__name__}: {exc})."
            )
            continue
        quote_value = qty * ticker.last
        holding_quote_values[coin] = quote_value
        holdings_value += quote_value

    if not holding_quote_values:
        raise ValueError(
            f"Every crypto holding failed to price against {quote}. "
            "Either the pairs aren't listed or the exchange is unreachable; "
            "see the terminal log for per-symbol errors."
        )

    total_equity = fiat_balance + holdings_value

    for coin, quote_value in sorted(
        holding_quote_values.items(), key=lambda kv: kv[1], reverse=True
    ):
        # Weight = the crypto allocation's share of total equity. Cash
        # is not an allocation; its weight is implicit (1 - sum(weights)).
        weight = float(quote_value / total_equity) if total_equity > 0 else 0.0
        allocations.append(
            Allocation(
                symbol=f"{coin}-{quote}",
                strategy_name=strategy_name,
                params={},
                weight=round(weight, 6),
                enabled=True,
            )
        )

    portfolio = Portfolio(
        name=name,
        timeframe=timeframe,
        initial_balance=total_equity,
        allocations=allocations,
    )

    logger.info(
        "portfolio_import_built",
        portfolio=name,
        quote=quote,
        total_equity=str(total_equity),
        allocations=len(allocations),
        skipped=len(skipped),
    )

    return ImportResult(
        portfolio=portfolio,
        quote_currency=quote,
        total_equity=total_equity,
        warnings=warnings,
        skipped=skipped,
    )
