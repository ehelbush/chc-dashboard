#!/usr/bin/env python3
"""
Schwab Data Sync Script
========================
Fetches account data from Schwab API and caches it as JSON for the dashboard.
Handles token refresh automatically. Falls back to cached data when tokens expire.

Usage:
    python3 schwab_sync.py              # Sync all data
    python3 schwab_sync.py --holdings   # Sync holdings only
    python3 schwab_sync.py --quotes     # Sync quotes only

Cache files are saved to data/schwab_cache.json and committed to the repo
so the Vercel-deployed dashboard can read them.
"""

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TOKEN_FILE = SCRIPT_DIR / "schwab_tokens.json"
CACHE_FILE = SCRIPT_DIR / "data" / "schwab_cache.json"
HISTORY_FILE = SCRIPT_DIR / "data" / "portfolio_history.json"
ENV_FILE = SCRIPT_DIR / ".env"

# Schwab API base URLs
TRADER_BASE = "https://api.schwabapi.com/trader/v1"
MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def save_tokens(tokens):
    tokens["saved_at"] = datetime.now(timezone.utc).isoformat()
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def refresh_access_token(tokens, app_key, app_secret):
    """Refresh the access token if needed."""
    now = time.time()

    # Check if access token is still valid (with 2 min buffer)
    if now < tokens.get("expires_at", 0) - 120:
        return tokens

    # Check if refresh token is still valid
    if now > tokens.get("refresh_expires_at", 0):
        print("  [!] Refresh token expired. Run: python3 schwab_auth.py")
        return None

    print("  Refreshing access token...")
    creds = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()

    req = urllib.request.Request(
        "https://api.schwabapi.com/v1/oauth/token",
        data=data, method="POST"
    )
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            new_tokens = json.loads(resp.read().decode())
            if "access_token" in new_tokens:
                new_tokens["refresh_expires_at"] = tokens.get("refresh_expires_at", 0)
                new_tokens["expires_at"] = now + new_tokens.get("expires_in", 1800)
                save_tokens(new_tokens)
                print("  Access token refreshed.")
                return new_tokens
    except Exception as e:
        print(f"  [!] Token refresh failed: {e}")

    return None


def schwab_get(endpoint, access_token, base=TRADER_BASE):
    """Make an authenticated GET request to the Schwab API."""
    url = f"{base}{endpoint}" if not endpoint.startswith("http") else endpoint
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [!] API error {e.code} for {endpoint}: {body[:200]}")
        return None
    except Exception as e:
        print(f"  [!] Request failed for {endpoint}: {e}")
        return None


def load_cache():
    """Load existing cache."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {"synced_at": None, "status": "no_data", "accounts": []}


def save_cache(cache_data):
    """Save cache to JSON file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache_data, indent=2))
    print(f"  Cache saved to {CACHE_FILE}")


def fetch_accounts(access_token):
    """Fetch all account numbers and hashes."""
    data = schwab_get("/accounts/accountNumbers", access_token)
    if not data:
        return []
    return data  # List of {accountNumber, hashValue}


def fetch_account_details(access_token, account_hash):
    """Fetch full account details including positions."""
    data = schwab_get(f"/accounts/{account_hash}?fields=positions", access_token)
    return data


def fetch_transactions(access_token, account_hash, days=90):
    """Fetch recent transactions."""
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(end.timestamp() - days * 86400, tz=timezone.utc)
    start_str = start.strftime("%Y-%m-%dT00:00:00.000Z")
    end_str = end.strftime("%Y-%m-%dT23:59:59.000Z")

    data = schwab_get(
        f"/accounts/{account_hash}/transactions?startDate={start_str}&endDate={end_str}&types=TRADE",
        access_token
    )
    return data or []


def fetch_quotes(access_token, symbols):
    """Fetch current quotes for a list of symbols."""
    if not symbols:
        return {}
    # Schwab API accepts comma-separated symbols
    sym_str = ",".join(symbols[:50])  # API limit per request
    data = schwab_get(f"/quotes?symbols={sym_str}&indicative=false", access_token, base=MARKET_BASE)
    return data or {}


def fetch_price_history(access_token, symbol, period_type="year", period=1, frequency_type="daily", frequency=1):
    """Fetch historical price data for a symbol."""
    params = urllib.parse.urlencode({
        "periodType": period_type,
        "period": period,
        "frequencyType": frequency_type,
        "frequency": frequency,
    })
    data = schwab_get(f"/pricehistory?symbol={symbol}&{params}", access_token, base=MARKET_BASE)
    return data


def compute_benchmarks(access_token, portfolio_symbols, portfolio_weights):
    """Fetch benchmark data (SPY, QQQ) and compute comparison metrics."""
    benchmarks = {}
    benchmark_symbols = ["SPY", "QQQ", "IWM", "DIA"]  # S&P 500, Nasdaq 100, Russell 2000, Dow 30

    for sym in benchmark_symbols:
        hist = fetch_price_history(access_token, sym, period_type="year", period=5)
        if hist and "candles" in hist:
            candles = hist["candles"]
            if len(candles) > 252:
                # 1-year return
                yr_ago = candles[-253]["close"] if len(candles) >= 253 else candles[0]["close"]
                current = candles[-1]["close"]
                one_yr_return = (current / yr_ago) - 1 if yr_ago > 0 else 0

                # YTD return
                jan1_idx = 0
                for i, c in enumerate(candles):
                    dt = datetime.fromtimestamp(c["datetime"] / 1000, tz=timezone.utc)
                    if dt.year == datetime.now().year:
                        jan1_idx = i
                        break
                ytd_return = (current / candles[jan1_idx]["close"]) - 1 if candles[jan1_idx]["close"] > 0 else 0

                # Annualized return (from full period)
                total_return = current / candles[0]["close"] - 1 if candles[0]["close"] > 0 else 0
                years = len(candles) / 252
                ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

                # Max drawdown
                peak = candles[0]["close"]
                max_dd = 0
                for c in candles:
                    peak = max(peak, c["close"])
                    dd = (c["close"] / peak) - 1
                    max_dd = min(max_dd, dd)

                benchmarks[sym] = {
                    "symbol": sym,
                    "current_price": round(current, 2),
                    "one_yr_return": round(one_yr_return, 4),
                    "ytd_return": round(ytd_return, 4),
                    "annualized_return": round(ann_return, 4),
                    "max_drawdown": round(max_dd, 4),
                    "data_points": len(candles),
                }

    return benchmarks


def compute_sector_breakdown(positions):
    """Compute sector allocation from positions (using asset type as proxy)."""
    sectors = {}
    total_value = 0

    for pos in positions:
        instrument = pos.get("instrument", {})
        asset_type = instrument.get("assetType", "UNKNOWN")
        market_value = abs(pos.get("marketValue", 0))
        symbol = instrument.get("symbol", "???")

        # Map common ETFs to sectors
        etf_sectors = {
            "XLE": "Energy", "XLF": "Financials", "XLK": "Technology",
            "XLV": "Healthcare", "XLI": "Industrials", "XLP": "Consumer Staples",
            "XLY": "Consumer Discretionary", "XLB": "Materials", "XLU": "Utilities",
            "XLRE": "Real Estate", "XLC": "Communication Services",
            "SPY": "Broad Market", "QQQ": "Broad Market (Tech-heavy)",
            "IWF": "Broad Market (Growth)", "IWM": "Broad Market (Small Cap)",
            "GLDM": "Commodities (Gold)", "SIVR": "Commodities (Silver)",
            "USO": "Commodities (Oil)", "XLE": "Energy",
        }

        sector = etf_sectors.get(symbol, asset_type)
        sectors.setdefault(sector, {"value": 0, "positions": []})
        sectors[sector]["value"] += market_value
        sectors[sector]["positions"].append(symbol)
        total_value += market_value

    # Convert to percentages
    result = {}
    for sector, data in sectors.items():
        result[sector] = {
            "value": round(data["value"], 2),
            "weight": round(data["value"] / total_value, 4) if total_value > 0 else 0,
            "positions": data["positions"],
        }

    return {"sectors": result, "total_value": round(total_value, 2)}


def append_history(cache):
    """Append a daily snapshot to portfolio_history.json for performance tracking."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load existing history
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            history = []

    summary = cache.get("portfolio_summary", {})
    total_value = summary.get("total_value", 0)
    total_equity = summary.get("total_equity", 0)
    total_cash = summary.get("total_cash", 0)

    # Estimate net flows: value change minus market-driven gain
    # Use total_value (not total_equity) since backfilled data may have inaccurate equity
    day_gain = sum(a.get("day_gain", 0) for a in cache.get("accounts", []))
    net_flows = 0
    if history:
        prev = history[-1]
        prev_value = prev.get("total_value", prev.get("total_equity", total_value))
        value_change = total_value - prev_value
        net_flows = round(value_change - day_gain, 2)

    # Build lightweight holdings snapshot
    holdings = []
    for acct in cache.get("accounts", []):
        for h in acct.get("holdings", []):
            holdings.append({
                "symbol": h["symbol"],
                "market_value": h["market_value"],
                "weight": round(h["market_value"] / total_value, 4) if total_value > 0 else 0,
                "quantity": h["quantity"],
            })

    # Benchmark prices
    benchmarks = cache.get("benchmarks", {})
    benchmark_prices = {sym: bm.get("current_price", 0) for sym, bm in benchmarks.items()}

    snapshot = {
        "date": today,
        "total_value": round(total_value, 2),
        "total_equity": round(total_equity, 2),
        "cash_balance": round(total_cash, 2),
        "net_flows": net_flows,
        "day_gain": round(day_gain, 2),
        "positions_count": summary.get("positions_count", 0),
        "holdings": holdings,
        "benchmark_prices": benchmark_prices,
    }

    # Update existing entry for today, or append new one
    updated = False
    for i, entry in enumerate(history):
        if entry.get("date") == today:
            history[i] = snapshot
            updated = True
            break
    if not updated:
        history.append(snapshot)

    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    print(f"  Portfolio history {'updated' if updated else 'appended'} for {today} ({len(history)} total entries)")


def backfill_missing_days(access_token):
    """Fill any gaps in portfolio_history.json using Schwab price history.

    Looks at the last entry, gets the holdings from it, fetches daily prices
    for each symbol since then, and computes portfolio value for each missing
    trading day.
    """
    if not HISTORY_FILE.exists():
        print("  No history file to backfill from.")
        return

    history = json.loads(HISTORY_FILE.read_text())
    if not history:
        return

    existing_dates = {e["date"] for e in history}
    last_entry = history[-1]
    last_date = last_entry["date"]
    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y-%m-%d")

    # Nothing to backfill if last entry is today
    days_gap = (today - last_dt.replace(tzinfo=timezone.utc)).days
    if days_gap <= 1:
        print(f"  History is current (last entry: {last_date}). No backfill needed.")
        return

    print(f"  Last history entry: {last_date} ({days_gap} days ago). Backfilling...")

    # Get positions from last entry
    positions = {}
    for h in last_entry.get("holdings", []):
        sym = h.get("symbol")
        qty = h.get("quantity", 0)
        if sym and qty:
            positions[sym] = qty

    if not positions:
        print("  [!] No positions in last history entry. Cannot backfill.")
        return

    # Fetch daily price history for each symbol since last_date
    # Use period that covers the gap
    symbols = list(positions.keys()) + ["SPY", "QQQ"]
    price_data = {}  # {symbol: {date_str: close_price}}

    for sym in symbols:
        # Fetch enough history to cover the gap
        # Use startDate/endDate for precise control
        start_ms = int(last_dt.timestamp() * 1000)
        end_ms = int(today.timestamp() * 1000)
        params = urllib.parse.urlencode({
            "periodType": "month",
            "frequencyType": "daily",
            "frequency": 1,
            "startDate": start_ms,
            "endDate": end_ms,
        })
        hist = schwab_get(f"/pricehistory?symbol={sym}&{params}", access_token, base=MARKET_BASE)

        if hist and "candles" in hist:
            sym_prices = {}
            for candle in hist["candles"]:
                ts = candle.get("datetime", 0) / 1000
                d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                sym_prices[d] = candle.get("close", 0)
            price_data[sym] = sym_prices
            print(f"    {sym}: {len(sym_prices)} daily prices")
        else:
            print(f"    {sym}: no price data returned")

        time.sleep(0.3)  # Rate limit

    if not price_data:
        print("  [!] No price data fetched. Cannot backfill.")
        return

    # Find all trading dates where we have prices for ALL position symbols
    position_syms = set(positions.keys())
    all_dates = set()
    for sym in position_syms:
        if sym in price_data:
            all_dates.update(price_data[sym].keys())
    # Only keep dates where ALL position symbols have prices
    for sym in position_syms:
        if sym in price_data:
            all_dates &= set(price_data[sym].keys())

    # Filter to dates after last_date and not already in history
    new_dates = sorted(d for d in all_dates if d > last_date and d not in existing_dates)

    if not new_dates:
        print("  No new trading days to backfill.")
        return

    print(f"  Backfilling {len(new_dates)} trading days: {new_dates[0]} to {new_dates[-1]}")

    # Use the last known total_value to compute day_gain / net_flows
    prev_value = last_entry.get("total_value", 0)

    new_entries = []
    for date_str in new_dates:
        total_value = 0
        holdings_snap = []
        for sym, qty in positions.items():
            if sym not in price_data or date_str not in price_data[sym]:
                continue
            price = price_data[sym][date_str]
            mv = round(qty * price, 2)
            total_value += mv
            holdings_snap.append({
                "symbol": sym,
                "market_value": mv,
                "weight": 0,
                "quantity": qty,
            })

        # Compute weights
        for h in holdings_snap:
            h["weight"] = round(h["market_value"] / total_value, 4) if total_value > 0 else 0

        # Day gain = change in value (assumes no cash flows between syncs)
        day_gain = round(total_value - prev_value, 2) if prev_value else 0

        # Benchmark prices
        bench = {}
        for sym in ["SPY", "QQQ"]:
            if sym in price_data and date_str in price_data[sym]:
                bench[sym] = round(price_data[sym][date_str], 2)

        entry = {
            "date": date_str,
            "total_value": round(total_value, 2),
            "total_equity": round(total_value, 2),
            "cash_balance": last_entry.get("cash_balance", 0),
            "net_flows": 0,
            "day_gain": day_gain,
            "positions_count": len(holdings_snap),
            "holdings": holdings_snap,
            "benchmark_prices": bench,
        }
        new_entries.append(entry)
        prev_value = total_value

    # Merge into history
    history.extend(new_entries)
    history.sort(key=lambda e: e["date"])
    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    print(f"  Backfilled {len(new_entries)} entries. Total history: {len(history)} entries.")


def sync_all(app_key, app_secret):
    """Main sync function — fetches everything and caches it."""
    tokens = load_tokens()
    if not tokens:
        print("  [!] No tokens found. Run: python3 schwab_auth.py")
        return False

    # Refresh if needed
    tokens = refresh_access_token(tokens, app_key, app_secret)
    if not tokens:
        print("  [!] Cannot authenticate. Using cached data.")
        return False

    access_token = tokens["access_token"]
    now = datetime.now(timezone.utc)

    print(f"\n  Syncing Schwab data at {now.strftime('%Y-%m-%d %H:%M UTC')}...")

    # 0. Backfill any missing days since last history entry
    print("\n  Checking for missing history days...")
    backfill_missing_days(access_token)

    # 1. Fetch accounts
    print("  Fetching accounts...")
    account_numbers = fetch_accounts(access_token)
    if not account_numbers:
        print("  [!] Could not fetch accounts.")
        return False

    print(f"  Found {len(account_numbers)} account(s)")

    cache = {
        "synced_at": now.isoformat(),
        "status": "live",
        "accounts": [],
        "benchmarks": {},
        "portfolio_summary": {},
    }

    all_symbols = set()

    # 2. Fetch each account's details
    for acct in account_numbers:
        acct_hash = acct.get("hashValue")
        acct_num = acct.get("accountNumber", "")
        masked_num = f"***{acct_num[-4:]}" if len(acct_num) >= 4 else "****"

        print(f"  Fetching account {masked_num}...")
        details = fetch_account_details(access_token, acct_hash)
        if not details:
            continue

        acct_data = details.get("securitiesAccount", details)
        positions = acct_data.get("positions", [])

        # Extract position data
        holdings = []
        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol", "???")
            all_symbols.add(symbol)

            holding = {
                "symbol": symbol,
                "name": instrument.get("description", symbol),
                "asset_type": instrument.get("assetType", "UNKNOWN"),
                "quantity": pos.get("longQuantity", 0) - pos.get("shortQuantity", 0),
                "avg_cost": round(pos.get("averagePrice", 0), 4),
                "market_value": round(pos.get("marketValue", 0), 2),
                "current_price": round(pos.get("marketValue", 0) / max(pos.get("longQuantity", 1), 1), 2),
                "day_gain_pct": round(pos.get("currentDayProfitLossPercentage", 0), 4),
                "total_gain": round(pos.get("longQuantity", 0) * (pos.get("marketValue", 0) / max(pos.get("longQuantity", 1), 1) - pos.get("averagePrice", 0)), 2) if pos.get("longQuantity", 0) > 0 else 0,
                "total_gain_pct": round((pos.get("marketValue", 0) / max(pos.get("longQuantity", 1) * pos.get("averagePrice", 1), 1) - 1), 4) if pos.get("averagePrice", 0) > 0 else 0,
            }
            holdings.append(holding)

        # Sort by market value descending
        holdings.sort(key=lambda h: abs(h["market_value"]), reverse=True)

        # Account balances
        balances = acct_data.get("currentBalances", acct_data.get("initialBalances", {}))

        # Sector breakdown
        sector_data = compute_sector_breakdown(positions)

        account_entry = {
            "account_id": masked_num,
            "account_type": acct_data.get("type", "UNKNOWN"),
            "holdings": holdings,
            "total_value": round(sum(h["market_value"] for h in holdings), 2),
            "cash_balance": round(balances.get("cashBalance", balances.get("availableFunds", 0)), 2),
            "total_equity": round(balances.get("liquidationValue", balances.get("equity", 0)), 2),
            "day_gain": round(sum(h.get("day_gain_pct", 0) * h["market_value"] / 100 for h in holdings), 2),
            "sectors": sector_data,
            "positions_count": len(holdings),
        }
        cache["accounts"].append(account_entry)

        # Fetch transactions
        print(f"  Fetching transactions for {masked_num}...")
        transactions = fetch_transactions(access_token, acct_hash, days=90)
        if transactions:
            recent_trades = []
            for txn in transactions[:50]:  # Keep last 50
                # Find the equity/ETF transfer item (skip currency/fee items)
                equity_item = None
                for item in txn.get("transferItems", []):
                    inst = item.get("instrument", {})
                    if inst.get("assetType") not in ("CURRENCY", "CASH_EQUIVALENT") and not item.get("feeType"):
                        equity_item = item
                        break

                symbol = ""
                quantity = 0
                action = ""
                if equity_item:
                    symbol = equity_item.get("instrument", {}).get("symbol", "")
                    quantity = equity_item.get("amount", 0)
                    effect = equity_item.get("positionEffect", "")
                    action = "BUY" if effect == "OPENING" else "SELL" if effect == "CLOSING" else txn.get("type", "")
                else:
                    # Non-trade transaction (dividend, transfer, etc.)
                    symbol = txn.get("description", "").split("~")[-1].strip() if "~" in txn.get("description", "") else ""
                    action = txn.get("type", "")

                if not symbol and txn.get("type") not in ("TRADE",):
                    continue  # Skip non-informative entries

                trade = {
                    "date": txn.get("tradeDate", txn.get("time", "")),
                    "type": action,
                    "description": txn.get("description", ""),
                    "symbol": symbol,
                    "amount": round(txn.get("netAmount", 0), 2),
                    "quantity": abs(quantity),
                }
                recent_trades.append(trade)
            account_entry["recent_trades"] = recent_trades

    # 3. Fetch quotes for all held symbols
    print(f"  Fetching quotes for {len(all_symbols)} symbols...")
    quotes = fetch_quotes(access_token, list(all_symbols))
    if quotes:
        cache["quotes"] = {
            sym: {
                "last_price": q.get("quote", {}).get("lastPrice", 0),
                "change": q.get("quote", {}).get("netChange", 0),
                "change_pct": q.get("quote", {}).get("netPercentChangeInDouble", 0),
                "volume": q.get("quote", {}).get("totalVolume", 0),
                "52w_high": q.get("quote", {}).get("52WkHigh", 0),
                "52w_low": q.get("quote", {}).get("52WkLow", 0),
            }
            for sym, q in quotes.items() if isinstance(q, dict)
        }

    # 3b. Fetch market cap from Yahoo Finance (not available in Schwab API)
    print(f"  Fetching market cap for {len(all_symbols)} symbols...")
    try:
        import yfinance as yf
        for sym in all_symbols:
            try:
                mc = yf.Ticker(sym).fast_info.market_cap
                if mc and mc > 0:
                    for acct in cache["accounts"]:
                        for h in acct.get("holdings", []):
                            if h["symbol"] == sym:
                                h["market_cap"] = mc
            except Exception:
                pass
    except ImportError:
        print("  [!] yfinance not installed — skipping market cap")

    # 4. Fetch benchmarks
    print("  Fetching benchmark data...")
    benchmarks = compute_benchmarks(access_token, list(all_symbols), {})
    cache["benchmarks"] = benchmarks

    # 5. Compute portfolio summary
    total_value = sum(a["total_value"] for a in cache["accounts"])
    total_cash = sum(a["cash_balance"] for a in cache["accounts"])
    total_equity = sum(a["total_equity"] for a in cache["accounts"])

    # Portfolio-weighted return
    all_holdings = []
    for acct in cache["accounts"]:
        all_holdings.extend(acct["holdings"])

    cache["portfolio_summary"] = {
        "total_value": round(total_value, 2),
        "total_cash": round(total_cash, 2),
        "total_equity": round(total_equity, 2),
        "positions_count": len(all_holdings),
        "accounts_count": len(cache["accounts"]),
        "top_holdings": [
            {"symbol": h["symbol"], "weight": round(h["market_value"] / total_value, 4) if total_value > 0 else 0, "value": h["market_value"]}
            for h in sorted(all_holdings, key=lambda x: abs(x["market_value"]), reverse=True)[:10]
        ],
    }

    # 6. Compute refresh token status for dashboard display
    refresh_expires = tokens.get("refresh_expires_at", 0)
    days_remaining = max(0, (refresh_expires - time.time()) / 86400)
    cache["auth_status"] = {
        "connected": True,
        "refresh_days_remaining": round(days_remaining, 1),
        "needs_reauth": days_remaining < 1,
        "last_sync": now.isoformat(),
    }

    # Save cache
    save_cache(cache)

    # Append to portfolio history for performance tracking
    append_history(cache)

    print(f"\n  Sync complete!")
    print(f"  {len(cache['accounts'])} account(s), {len(all_holdings)} positions")
    print(f"  Total portfolio value: ${total_value:,.2f}")
    print(f"  Refresh token valid for {days_remaining:.1f} more days")

    return True


def main():
    parser = argparse.ArgumentParser(description="Schwab Data Sync")
    parser.add_argument("--holdings", action="store_true", help="Sync holdings only")
    parser.add_argument("--quotes", action="store_true", help="Sync quotes only")
    args = parser.parse_args()

    env = load_env()
    app_key = env.get("SCHWAB_APP_KEY") or os.environ.get("SCHWAB_APP_KEY")
    app_secret = env.get("SCHWAB_APP_SECRET") or os.environ.get("SCHWAB_APP_SECRET")

    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║   CherryHead Capital — Schwab Data Sync      ║")
    print("  ╚══════════════════════════════════════════════╝")

    if not app_key or not app_secret:
        print("\n  [!] Missing SCHWAB_APP_KEY / SCHWAB_APP_SECRET in .env")
        sys.exit(1)

    success = sync_all(app_key, app_secret)
    if not success:
        cache = load_cache()
        if cache.get("synced_at"):
            print(f"\n  Using cached data from {cache['synced_at']}")
            cache["status"] = "cached"
            cache["auth_status"] = {
                "connected": False,
                "refresh_days_remaining": 0,
                "needs_reauth": True,
                "last_sync": cache["synced_at"],
            }
            save_cache(cache)
        else:
            print("\n  No cached data available. Authenticate first:")
            print("  python3 schwab_auth.py")


if __name__ == "__main__":
    main()
