#!/usr/bin/env python3
"""
Fetch all NYSE/NASDAQ tickers, run the CHC model, and save summary results.
Run this script periodically (e.g. weekly) to refresh the data.

Usage:
  cd chc-dashboard-web
  python3 fetch_all_tickers.py

Takes 1-3 hours depending on internet speed. Progress is saved continuously,
so you can stop and restart — it will skip tickers already fetched today.
"""
import sys, os, json, time, math
from datetime import datetime, timedelta

# Use the venv from chc-dashboard if available
venv_site = os.path.join(os.path.dirname(__file__), '..', 'chc-dashboard', 'venv', 'lib')
if os.path.exists(venv_site):
    for d in os.listdir(venv_site):
        sp = os.path.join(venv_site, d, 'site-packages')
        if os.path.exists(sp) and sp not in sys.path:
            sys.path.insert(0, sp)

import yfinance as yf
import numpy as np


# ── CHC Trading Model (Python port matching the JS version) ──────────────

def compute_chc_model(dates, closes, volumes, eval_years=5,
                      vol_flag=2, price_flag=1, vol_price_mix=0.72,
                      buy_threshold=0.0012, sell_threshold=-0.0012):
    n = len(closes)
    if n < 130:
        return None

    ma_windows = {0: 1, 1: 50, 2: 100, 3: 120}
    vol_window = ma_windows.get(vol_flag, 100)
    price_window = ma_windows.get(price_flag, 50)
    lookback = max(vol_window, price_window, 5)

    eval_days = eval_years * 252
    start_trim = max(0, n - eval_days)
    cl = np.array(closes[start_trim:], dtype=np.float64)
    vo = np.array(volumes[start_trim:], dtype=np.float64)
    dt = dates[start_trim:]
    N = len(cl)

    if N < lookback + 10:
        return None

    # Volume up/down
    vud = np.zeros(N)
    vud[0] = vo[0]
    for i in range(1, N):
        vud[i] = vo[i] if cl[i] >= cl[i-1] else -vo[i]

    # Volume ratio
    vr = np.ones(N)
    for i in range(vol_window, N):
        ss = np.sum(vud[i - vol_window + 1:i + 1])
        as_ = np.sum(vo[i - vol_window + 1:i + 1])
        if as_ > 0:
            vr[i] = ss / as_

    # Price MA
    pma = cl.copy()
    for i in range(price_window, N):
        pma[i] = np.mean(cl[i - price_window + 1:i + 1])

    # Price slope
    ps = np.zeros(N)
    for i in range(4, N):
        mid = pma[i-2] if pma[i-2] != 0 else 1
        ps[i] = (pma[i] - pma[i-4]) / mid

    # Combined signal
    comb = vol_price_mix * vr + (1 - vol_price_mix) * ps

    # Generate signals & balances
    signals = ["Hold"] * N
    bal = np.zeros(N)
    shares = np.zeros(N)
    bh_bal = np.zeros(N)
    init_bal = 100000
    si = lookback

    bal[si] = init_bal
    shares[si] = init_bal / cl[si] if cl[si] > 0 else 0
    signals[si] = "Buy"
    bh_shares = init_bal / cl[si] if cl[si] > 0 else 0

    for i in range(si, N):
        bh_bal[i] = bh_shares * cl[i]

    for i in range(si + 1, N):
        if comb[i] >= buy_threshold:
            signals[i] = "Buy"
        elif comb[i] <= sell_threshold:
            signals[i] = "Sell"
        else:
            signals[i] = signals[i-1]

        traded = signals[i] != signals[i-1]

        if signals[i] == "Buy":
            if traded:
                shares[i] = bal[i-1] / cl[i] if cl[i] > 0 else 0
                bal[i] = shares[i] * cl[i]
            else:
                shares[i] = shares[i-1]
                bal[i] = shares[i] * cl[i]
        elif signals[i] == "Sell":
            if traded:
                bal[i] = shares[i-1] * cl[i]
                shares[i] = 0
            else:
                shares[i] = 0
                bal[i] = bal[i-1]
        else:
            shares[i] = shares[i-1]
            bal[i] = shares[i] * cl[i] if shares[i] > 0 else bal[i-1]

    # Compute metrics
    def calc_metrics(b, start):
        vals = [v for v in b[start:] if v > 0]
        if len(vals) < 2:
            return {}
        max_b = vals[0]
        dd = []
        for v in vals:
            max_b = max(max_b, v)
            dd.append(v / max_b - 1)
        last_yr_days = min(252, len(vals) - 1)
        last_yr_ret = vals[-1] / vals[-1 - last_yr_days] - 1
        yrs = len(vals) / 252
        avg_yr_ret = (vals[-1] / vals[0]) ** (1 / yrs) - 1 if yrs > 0 and vals[0] > 0 else 0
        current_loss = dd[-1]
        max_loss = min(dd)
        avg_loss = np.mean(dd)
        std_loss = np.std(dd)
        stat3_loss = avg_loss - 3 * std_loss
        recovery = 0
        if max_loss < 0 and avg_yr_ret > 0:
            recovery = -2 * math.log(1 + max_loss) / math.log(1 + avg_yr_ret)
        return {
            "last_yr_return": round(last_yr_ret, 6),
            "avg_yr_return": round(avg_yr_ret, 6),
            "current_loss": round(current_loss, 6),
            "stat3_loss": round(stat3_loss, 6),
            "recovery_period": round(recovery, 2),
        }

    trading = calc_metrics(bal, si)
    call_strength = round(float(comb[N-1]), 6) if N > 0 else 0
    buy_signal = signals[N-1] if N > 0 else "Hold"
    est_next_yr = round((trading.get("last_yr_return", 0) + trading.get("avg_yr_return", 0)) / 2, 6)

    # Sanitize NaN/Infinity (not valid in JSON)
    def safe(v):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return 0
        return v

    return {
        "ticker": None,  # set by caller
        "buy_sell_call": buy_signal,
        "call_strength": safe(call_strength),
        "last_yr_return": safe(trading.get("last_yr_return", 0)),
        "av_yrly_return": safe(trading.get("avg_yr_return", 0)),
        "est_next_yr_return": safe(est_next_yr),
        "current_loss": safe(trading.get("current_loss", 0)),
        "stat3_loss": safe(trading.get("stat3_loss", 0)),
        "recovery_period": safe(trading.get("recovery_period", 0)),
    }


# ── Get ticker lists ─────────────────────────────────────────────────────

def get_all_tickers():
    """Get NYSE + NASDAQ tickers using multiple methods."""
    tickers = set()

    # Method 1: Try stock_info package
    try:
        from stock_info import get_tickers
        tickers.update(get_tickers.get_tickers())
        print(f"  stock_info: {len(tickers)} tickers")
    except:
        pass

    # Method 2: Download from public sources
    import requests

    # NASDAQ traded list
    try:
        url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
        r = requests.get(url, timeout=15)
        if r.ok:
            for line in r.text.strip().split('\n'):
                sym = line.strip().upper()
                if sym and sym.isalpha() and len(sym) <= 5:
                    tickers.add(sym)
            print(f"  GitHub list: {len(tickers)} tickers")
    except:
        pass

    # Method 3: S&P 500 + common large caps as fallback
    if len(tickers) < 100:
        try:
            import pandas as pd
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            if tables:
                for sym in tables[0]['Symbol']:
                    tickers.add(sym.replace('.', '-').upper())
                print(f"  S&P 500: {len(tickers)} tickers")
        except:
            pass

    # Method 4: Use yfinance screener as additional source
    # Add major ETFs and common tickers
    common = [
        "AAPL","MSFT","AMZN","GOOG","GOOGL","META","TSLA","NVDA","BRK-B",
        "JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","PYPL","BAC",
        "CMCSA","ADBE","NFLX","XOM","VZ","INTC","T","CRM","ABT","CSCO",
        "PFE","PEP","KO","NKE","MRK","TMO","ABBV","AVGO","ACN","COST",
        "DHR","TXN","MDT","LIN","BMY","AMGN","HON","NEE","UNP","PM",
        "RTX","LOW","SBUX","IBM","GE","CAT","LMT","GS","BLK","AXP",
        "AMD","QCOM","ISRG","AMAT","MU","LRCX","ADI","MRVL","KLAC",
        "SNPS","CDNS","FTNT","PANW","CRWD","ZS","NET","DDOG","SNOW",
        "PLTR","SQ","SHOP","MELI","SE","BABA","TSM","ASML","SAP",
        "SPY","QQQ","IWM","IWF","DIA","VTI","VOO","XLE","XLF","XLK",
        "GLDM","SIVR","USO","GLD","SLV","TLT","HYG","LQD",
        "ANET","LLY","NRG","RCL","TPR","AXON","WCLD","CRWV",
    ]
    tickers.update(common)

    # Filter out anything weird
    clean = set()
    for t in tickers:
        t = t.strip().upper()
        # Skip warrants, units, preferred shares, test symbols
        if any(c in t for c in [' ', '$', '^', '/', '+', '#']):
            continue
        if len(t) > 5 or len(t) == 0:
            continue
        clean.add(t)

    return sorted(clean)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    output_path = os.path.join(os.path.dirname(__file__), 'data', 'market_screener.json')

    # Load existing results (for resume capability)
    existing = {}
    today = datetime.now().strftime('%Y-%m-%d')
    if os.path.exists(output_path):
        with open(output_path) as f:
            data = json.load(f)
            if data.get("date") == today:
                existing = {r["ticker"]: r for r in data.get("results", [])}
                print(f"Resuming — {len(existing)} tickers already done today")

    print("Getting ticker list...")
    all_tickers = get_all_tickers()
    print(f"Found {len(all_tickers)} tickers to process")

    # Skip already-fetched tickers
    to_fetch = [t for t in all_tickers if t not in existing]
    print(f"Need to fetch {len(to_fetch)} new tickers\n")

    results = list(existing.values())
    errors = 0
    batch_size = 50
    start_time = time.time()

    for idx, sym in enumerate(to_fetch):
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="6y")

            if hist.empty or len(hist) < 130:
                errors += 1
                continue

            dates = [d.strftime('%Y-%m-%d') for d in hist.index]
            closes = hist['Close'].tolist()
            volumes = hist['Volume'].astype(int).tolist()

            result = compute_chc_model(dates, closes, volumes)
            if result is None:
                errors += 1
                continue

            result["ticker"] = sym
            try:
                result["market_cap"] = tk.fast_info.market_cap
            except Exception:
                result["market_cap"] = None
            try:
                info = tk.info
                result["sector"] = info.get("sector", "")
                result["industry"] = info.get("industry", "")
            except Exception:
                result["sector"] = ""
                result["industry"] = ""
            results.append(result)

        except Exception as e:
            errors += 1
            continue

        # Progress update
        done = idx + 1
        if done % 10 == 0 or done == len(to_fetch):
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(to_fetch) - done) / rate if rate > 0 else 0
            print(f"  [{done}/{len(to_fetch)}] {sym} — "
                  f"{len(results)} good, {errors} errors — "
                  f"ETA: {remaining/60:.0f} min")

        # Save progress every batch_size tickers
        if done % batch_size == 0 or done == len(to_fetch):
            output = {
                "date": today,
                "generated": datetime.now().isoformat(),
                "total_tickers": len(results),
                "results": sorted(results, key=lambda r: r.get("recovery_period", 999)),
            }
            with open(output_path, 'w') as f:
                json.dump(output, f, separators=(',', ':'))

        # Small delay to avoid rate limiting
        time.sleep(0.2)

    # Final save
    output = {
        "date": today,
        "generated": datetime.now().isoformat(),
        "total_tickers": len(results),
        "results": sorted(results, key=lambda r: r.get("recovery_period", 999)),
    }
    with open(output_path, 'w') as f:
        json.dump(output, f, separators=(',', ':'))

    elapsed = time.time() - start_time
    print(f"\nDone! {len(results)} tickers processed in {elapsed/60:.1f} minutes")
    print(f"Errors/skipped: {errors}")
    print(f"Output: {output_path} ({os.path.getsize(output_path)/1024:.0f} KB)")
    print(f"\nPush to GitHub:")
    print(f"  git add data/market_screener.json")
    print(f'  git commit -m "Update market screener data {today}"')
    print(f"  git push")


if __name__ == '__main__':
    main()
