#!/usr/bin/env python3
"""Add a ticker to the pre-loaded tickers.json data file."""
import sys, os, json

# Use the venv from chc-dashboard if available
venv_site = os.path.join(os.path.dirname(__file__), '..', 'chc-dashboard', 'venv', 'lib')
if os.path.exists(venv_site):
    for d in os.listdir(venv_site):
        sp = os.path.join(venv_site, d, 'site-packages')
        if os.path.exists(sp) and sp not in sys.path:
            sys.path.insert(0, sp)

import yfinance as yf
import numpy as np

def add_ticker(symbol, years=6):
    symbol = symbol.upper().strip()
    data_path = os.path.join(os.path.dirname(__file__), 'data', 'tickers.json')

    # Load existing data
    if os.path.exists(data_path):
        with open(data_path) as f:
            all_data = json.load(f)
    else:
        all_data = {}

    print(f"Fetching {years} years of data for {symbol}...")
    tk = yf.Ticker(symbol)
    hist = tk.history(period=f"{years}y")

    if hist.empty or len(hist) < 130:
        print(f"Error: Not enough data for {symbol} (got {len(hist)} days, need 130+)")
        return False

    dates = [d.strftime('%Y-%m-%d') for d in hist.index]
    closes = [round(float(c), 4) for c in hist['Close']]
    volumes = [int(v) for v in hist['Volume']]

    all_data[symbol] = {
        "s": symbol,
        "d": dates,
        "c": closes,
        "v": volumes
    }

    with open(data_path, 'w') as f:
        json.dump(all_data, f, separators=(',', ':'))

    print(f"Added {symbol} ({len(dates)} days) to tickers.json")
    print(f"File size: {os.path.getsize(data_path) / 1024:.0f} KB")
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 add_ticker.py TICKER [TICKER2 ...]")
        print("Example: python3 add_ticker.py HD MSFT AMZN")
        sys.exit(1)

    for sym in sys.argv[1:]:
        add_ticker(sym)

    print("\nDone! Now push to GitHub:")
    print("  git add data/tickers.json")
    print('  git commit -m "Add ticker data"')
    print("  git push")
