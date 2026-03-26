#!/usr/bin/env python3
"""
Backfill portfolio history from Schwab data.

Uses the Schwab balance export CSV as the source of truth for total account value,
and reconstructs position-level detail from Schwab API transactions + price history.

Data sources:
  - Balance CSV: Exported from Schwab, gives actual daily account balance (equity + cash)
  - Schwab API transactions: Used to reconstruct what positions were held on each date
  - Schwab API / tickers.json price history: Used to value individual positions

Usage:
    python3 backfill_history.py [path_to_balance_csv]
"""

import csv
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from schwab_sync import (
    load_env,
    load_tokens,
    refresh_access_token,
    schwab_get,
    TRADER_BASE,
    MARKET_BASE,
)

CACHE_FILE = SCRIPT_DIR / "data" / "schwab_cache.json"
HISTORY_FILE = SCRIPT_DIR / "data" / "portfolio_history.json"


def fetch_all_transactions(access_token, account_hash, start_date, end_date):
    """Fetch all transactions in a date range. Schwab limits to ~1 year per call."""
    all_txns = []
    current_start = start_date

    while current_start < end_date:
        # Schwab API strictly enforces < 1 year per request
        current_end = min(current_start + timedelta(days=364), end_date)
        start_str = current_start.strftime("%Y-%m-%dT00:00:00.000Z")
        end_str = current_end.strftime("%Y-%m-%dT23:59:59.000Z")

        print(f"  Fetching transactions {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}...")
        data = schwab_get(
            f"/accounts/{account_hash}/transactions?startDate={start_str}&endDate={end_str}",
            access_token
        )

        if data and isinstance(data, list):
            all_txns.extend(data)
            print(f"    Got {len(data)} transactions")
        elif data is None:
            print(f"    No data returned for this period")

        current_start = current_end + timedelta(days=1)
        time.sleep(0.5)  # Rate limit

    return all_txns


def parse_transactions(transactions):
    """Parse Schwab transactions into a list of position changes by date.

    Schwab TRADE transferItems contain:
    - Fee entries (COMMISSION, SEC_FEE, etc.) with symbol CURRENCY_USD — skip these
    - The actual equity/etf item with assetType EQUITY/ETF, positionEffect OPENING/CLOSING
      and amount = signed quantity change (negative for sells)

    Also tracks cash flows (WIRE_IN, ELECTRONIC_FUND, CASH_DISBURSEMENT) for net_flows.

    Returns list of {date, symbol, quantity_change, amount, type} sorted by date ascending.
    """
    changes = []
    cash_flows = []  # Track deposits/withdrawals

    for txn in transactions:
        txn_date = txn.get("tradeDate", txn.get("time", ""))
        if not txn_date:
            continue

        # Parse date — Schwab returns ISO format with +0000 (no colon)
        try:
            # Normalize timezone: +0000 -> +00:00, Z -> +00:00
            normalized = txn_date.replace("Z", "+00:00")
            # Fix +0000 / -0500 style offsets (missing colon)
            import re
            normalized = re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', normalized)
            dt = datetime.fromisoformat(normalized)
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        txn_type = txn.get("type", "")
        net_amount = txn.get("netAmount", 0)

        # Track cash flows (deposits/withdrawals)
        if txn_type in ("WIRE_IN", "WIRE_OUT", "ELECTRONIC_FUND", "CASH_DISBURSEMENT"):
            cash_flows.append({
                "date": date_str,
                "amount": net_amount,
                "type": txn_type,
                "description": txn.get("description", ""),
            })
            continue

        # Only process TRADE and RECEIVE_AND_DELIVER for position changes
        if txn_type not in ("TRADE", "RECEIVE_AND_DELIVER"):
            continue

        # Process transfer items — look for non-currency, non-fee entries
        transfer_items = txn.get("transferItems", [])
        for item in transfer_items:
            instrument = item.get("instrument", {})
            symbol = instrument.get("symbol", "")
            asset_type = instrument.get("assetType", "")

            # Skip currency entries (fees, cash legs) and money market
            if not symbol or asset_type in ("CURRENCY", "CASH_EQUIVALENT"):
                continue
            if symbol == "CURRENCY_USD":
                continue
            # Skip fee entries
            if item.get("feeType"):
                continue

            qty = item.get("amount", 0)
            # amount is already signed: positive for buys, negative for sells
            # positionEffect confirms: OPENING = buy, CLOSING = sell

            if qty != 0:
                changes.append({
                    "date": date_str,
                    "symbol": symbol,
                    "quantity_change": qty,
                    "type": txn_type,
                    "amount": net_amount,
                })

    # Sort by date ascending
    changes.sort(key=lambda c: c["date"])
    cash_flows.sort(key=lambda c: c["date"])

    # Print cash flow summary
    if cash_flows:
        print(f"\n  Cash flows found: {len(cash_flows)}")
        for cf in cash_flows:
            print(f"    {cf['date']}: ${cf['amount']:+,.2f} ({cf['type']})")

    return changes, cash_flows


def reconstruct_positions(current_holdings, transaction_changes):
    """Given current holdings and historical transactions, reconstruct
    positions at each date going backwards.

    Returns: {date_str: {symbol: quantity}} for each trading day.
    """
    # Start with current positions
    positions = {}
    for h in current_holdings:
        if h["quantity"] != 0:
            positions[h["symbol"]] = h["quantity"]

    print(f"  Current positions: {len(positions)} symbols")

    # Work backwards through transactions to undo each change
    # Sort changes by date descending for backwards walk
    changes_desc = sorted(transaction_changes, key=lambda c: c["date"], reverse=True)

    # Group changes by date
    dates_with_changes = {}
    for c in changes_desc:
        dates_with_changes.setdefault(c["date"], []).append(c)

    # Build position snapshots at each change date
    snapshots = {}
    # The "current" snapshot is today
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshots[today] = dict(positions)

    for date_str in sorted(dates_with_changes.keys(), reverse=True):
        day_changes = dates_with_changes[date_str]
        # Undo this day's changes to get the position BEFORE this date
        for c in day_changes:
            sym = c["symbol"]
            qty_change = c["quantity_change"]
            current_qty = positions.get(sym, 0)
            # Undo: subtract the change that happened
            new_qty = current_qty - qty_change
            if abs(new_qty) < 0.001:
                positions.pop(sym, None)
            else:
                positions[sym] = new_qty

        # Record the position state as of the day before this change
        prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        snapshots[prev_date] = dict(positions)

    return snapshots


def fetch_price_history_bulk(access_token, symbols, start_date, end_date):
    """Fetch daily price history from Schwab for multiple symbols.

    Returns: {symbol: {date_str: close_price}}
    """
    prices = {}

    for sym in symbols:
        print(f"  Fetching price history for {sym}...")
        params = urllib.parse.urlencode({
            "periodType": "year",
            "period": 10,  # Max we can get
            "frequencyType": "daily",
            "frequency": 1,
        })
        data = schwab_get(
            f"/pricehistory?symbol={sym}&{params}",
            access_token, base=MARKET_BASE
        )

        if data and "candles" in data:
            sym_prices = {}
            for candle in data["candles"]:
                ts = candle.get("datetime", 0)
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
                sym_prices[date_str] = candle["close"]
            prices[sym] = sym_prices
            print(f"    {sym}: {len(sym_prices)} days of prices")
        else:
            print(f"    {sym}: no price data available")

        time.sleep(0.3)  # Rate limit

    return prices


def load_balance_csv(csv_path):
    """Load Schwab balance export CSV.

    Returns: {date_str: balance} where date_str is YYYY-MM-DD.
    """
    balances = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_parts = row["Date"].split("/")
            date_str = f"{date_parts[2]}-{int(date_parts[0]):02d}-{int(date_parts[1]):02d}"
            amount = float(row["Amount"].replace("$", "").replace(",", ""))
            balances[date_str] = amount
    return balances


def build_daily_history(schwab_balances, position_snapshots, price_data, cash_flows, benchmark_symbols):
    """Build daily portfolio history using Schwab balance CSV as source of truth.

    - total_value comes directly from the Schwab balance CSV
    - Holdings breakdown is computed from reconstructed positions × prices
    - Cash balance = total_value - computed equity value
    - Net flows are derived from the cash flow transactions
    """
    # Build cash flow lookup by date
    flow_by_date = {}
    for cf in cash_flows:
        flow_by_date.setdefault(cf["date"], 0)
        flow_by_date[cf["date"]] += cf["amount"]

    # Get snapshot dates sorted for position lookup
    snap_dates = sorted(position_snapshots.keys())

    # Process each date in the balance CSV
    dates = sorted(schwab_balances.keys())
    history = []
    prev_total = None

    for date in dates:
        total_value = schwab_balances[date]

        # Find the applicable position snapshot
        applicable_snap = None
        for sd in snap_dates:
            if sd <= date:
                applicable_snap = sd
            else:
                break

        # Compute equity from positions
        equity_value = 0
        holdings_snap = []

        if applicable_snap is not None:
            positions = position_snapshots[applicable_snap]
            for sym, qty in positions.items():
                if sym in price_data and date in price_data[sym]:
                    price = price_data[sym][date]
                    mv = round(qty * price, 2)
                    equity_value += mv
                    holdings_snap.append({
                        "symbol": sym,
                        "market_value": mv,
                        "weight": 0,
                        "quantity": qty,
                    })

        # Compute weights based on total_value from Schwab
        for h in holdings_snap:
            h["weight"] = round(h["market_value"] / total_value, 4) if total_value > 0 else 0

        # Cash = total - equity
        cash_balance = round(total_value - equity_value, 2)

        # Net flows for this date
        net_flows = round(flow_by_date.get(date, 0), 2)

        # Day gain = change in value minus net flows
        day_gain = 0
        if prev_total is not None:
            day_gain = round(total_value - prev_total - net_flows, 2)

        # Benchmark prices
        bench = {}
        for sym in benchmark_symbols:
            if sym in price_data and date in price_data[sym]:
                bench[sym] = round(price_data[sym][date], 2)

        entry = {
            "date": date,
            "total_value": round(total_value, 2),
            "total_equity": round(equity_value, 2),
            "cash_balance": cash_balance,
            "net_flows": net_flows,
            "day_gain": day_gain,
            "positions_count": len(holdings_snap),
            "holdings": holdings_snap,
            "benchmark_prices": bench,
        }
        history.append(entry)
        prev_total = total_value

    return history


def main():
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║   Portfolio History Backfill (Schwab Data)    ║")
    print("  ╚══════════════════════════════════════════════╝\n")

    # Find balance CSV
    balance_csv = None
    if len(sys.argv) > 1:
        balance_csv = sys.argv[1]
    else:
        # Look in Downloads for the most recent Schwab balance export
        downloads = Path.home() / "Downloads"
        csvs = sorted(downloads.glob("*Balances*.CSV"), key=lambda p: p.stat().st_mtime, reverse=True)
        if csvs:
            balance_csv = str(csvs[0])

    if not balance_csv or not Path(balance_csv).exists():
        print("  [!] No Schwab balance CSV found.")
        print("  Usage: python3 backfill_history.py <path_to_balance_csv>")
        print("  Or place the CSV in ~/Downloads/")
        sys.exit(1)

    print(f"  Balance CSV: {balance_csv}")

    # Load Schwab balances
    schwab_balances = load_balance_csv(balance_csv)
    dates = sorted(schwab_balances.keys())
    print(f"  Date range: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    print(f"  Starting balance: ${schwab_balances[dates[0]]:,.2f}")
    print(f"  Ending balance: ${schwab_balances[dates[-1]]:,.2f}")

    # Auth setup
    env = load_env()
    app_key = env.get("SCHWAB_APP_KEY") or os.environ.get("SCHWAB_APP_KEY")
    app_secret = env.get("SCHWAB_APP_SECRET") or os.environ.get("SCHWAB_APP_SECRET")

    if not app_key or not app_secret:
        print("  [!] Missing SCHWAB_APP_KEY / SCHWAB_APP_SECRET in .env")
        sys.exit(1)

    tokens = load_tokens()
    if not tokens:
        print("  [!] No tokens found. Run: python3 schwab_auth.py")
        sys.exit(1)

    tokens = refresh_access_token(tokens, app_key, app_secret)
    if not tokens:
        print("  [!] Cannot authenticate.")
        sys.exit(1)

    access_token = tokens["access_token"]

    # Load current holdings from cache
    cache = json.loads(CACHE_FILE.read_text())
    current_holdings = cache["accounts"][0]["holdings"]
    print(f"\n  Current holdings: {len(current_holdings)} positions")
    for h in current_holdings:
        print(f"    {h['symbol']}: {h['quantity']} shares @ ${h['avg_cost']:.2f}")

    # Step 1: Fetch accounts
    from schwab_sync import fetch_accounts
    account_numbers = fetch_accounts(access_token)
    if not account_numbers:
        print("  [!] Could not fetch accounts.")
        sys.exit(1)

    account_hash = account_numbers[0]["hashValue"]

    # Step 2: Load or fetch transactions
    txn_file = SCRIPT_DIR / "data" / "schwab_transactions.json"
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=5 * 365)

    if txn_file.exists():
        print(f"\n  Loading cached transactions from {txn_file}...")
        all_txns = json.loads(txn_file.read_text())
        print(f"  Loaded {len(all_txns)} cached transactions")
    else:
        print(f"\n  Fetching transactions from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")
        all_txns = fetch_all_transactions(access_token, account_hash, start_date, end_date)
        print(f"  Total transactions fetched: {len(all_txns)}")
        if all_txns:
            txn_file.write_text(json.dumps(all_txns, indent=2))
            print(f"  Raw transactions saved to {txn_file}")

    # Step 3: Parse transactions
    changes, cash_flows = parse_transactions(all_txns)
    print(f"\n  Parsed {len(changes)} position changes")
    if changes:
        print(f"  Earliest change: {changes[0]['date']}")
        print(f"  Latest change: {changes[-1]['date']}")
        symbols_changed = set(c["symbol"] for c in changes)
        print(f"  Symbols traded: {len(symbols_changed)}")

    # Step 4: Reconstruct historical positions
    print(f"\n  Reconstructing historical positions...")
    snapshots = reconstruct_positions(current_holdings, changes)
    print(f"  Position snapshots: {len(snapshots)} dates")

    # Step 5: Collect all symbols needing price data
    all_symbols = set()
    for positions in snapshots.values():
        all_symbols.update(positions.keys())

    benchmark_symbols = ["SPY", "QQQ"]
    all_symbols.update(benchmark_symbols)

    # Filter out CUSIP-style identifiers (they won't have price data)
    all_symbols = {s for s in all_symbols if not s[0].isdigit()}

    print(f"\n  Need price history for {len(all_symbols)} symbols")

    # Step 6: Load prices from tickers.json cache, fetch missing from Schwab
    TICKERS_FILE = SCRIPT_DIR / "data" / "tickers.json"
    price_data = {}
    missing_symbols = set(all_symbols)

    if TICKERS_FILE.exists():
        tickers = json.loads(TICKERS_FILE.read_text())
        for sym in list(missing_symbols):
            if sym in tickers:
                t = tickers[sym]
                price_data[sym] = dict(zip(t["d"], t["c"]))
                missing_symbols.discard(sym)

        print(f"  Loaded {len(all_symbols) - len(missing_symbols)} symbols from tickers.json")

    # Cache Schwab price data to avoid re-fetching
    price_cache_file = SCRIPT_DIR / "data" / "schwab_prices_cache.json"
    if price_cache_file.exists():
        cached_prices = json.loads(price_cache_file.read_text())
        for sym in list(missing_symbols):
            if sym in cached_prices:
                price_data[sym] = cached_prices[sym]
                missing_symbols.discard(sym)
        print(f"  Loaded {len(all_symbols) - len(missing_symbols) - (len(all_symbols) - len(missing_symbols))} additional symbols from price cache")

    if missing_symbols:
        print(f"\n  Fetching price history from Schwab for {len(missing_symbols)} symbols...")
        schwab_prices = fetch_price_history_bulk(access_token, sorted(missing_symbols), start_date, end_date)
        price_data.update(schwab_prices)

        # Cache the fetched prices
        all_cached = {}
        if price_cache_file.exists():
            all_cached = json.loads(price_cache_file.read_text())
        all_cached.update(schwab_prices)
        price_cache_file.write_text(json.dumps(all_cached))
        print(f"  Price cache saved ({len(all_cached)} symbols)")

    # Step 7: Build daily history using Schwab balance CSV as source of truth
    print(f"\n  Building daily portfolio history...")
    history = build_daily_history(schwab_balances, snapshots, price_data, cash_flows, benchmark_symbols)
    print(f"  Generated {len(history)} daily entries")

    if history:
        print(f"  Date range: {history[0]['date']} to {history[-1]['date']}")
        print(f"  Starting value: ${history[0]['total_value']:,.2f}")
        print(f"  Ending value: ${history[-1]['total_value']:,.2f}")

    # Step 8: Save — backfilled data replaces everything in its date range
    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    print(f"\n  Saved {len(history)} entries to {HISTORY_FILE}")


if __name__ == "__main__":
    main()
