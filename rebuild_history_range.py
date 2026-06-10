#!/usr/bin/env python3
"""Rebuild portfolio_history.json over a date range from ground-truth account data.

Generalizes rebuild_gap_history.py to any range the transaction ledger covers.
Reconstructs each trading day by:
  - HOLDINGS: backward trade-replay from the current positions CSV (exact shares).
  - CASH: ledger anchored to the 04/01 statement opening cash ($839.04).
  - NET FLOWS: external transfers only (Wire Received / Funds Paid) from the ledger;
    dividends/interest are income, not flows.
  - PRICES: Schwab pricehistory daily closes.
  - BENCHMARKS: SPY, QQQ, IWM, DIA, and $COMPX (Nasdaq Composite, stored as COMPX).

Replaces existing entries in [START_DATE, live_date); keeps the live (last) entry
and anything before START_DATE. Dry-run by default; --write applies (.json.bak first).
"""
import csv
import json
import time
import urllib.parse
from datetime import datetime, timezone

import schwab_sync as s

START_DATE = "2025-12-19"          # transaction ledger start (earliest reliable date)
CASH_ANCHOR_DATE = "2026-03-31"    # end of 3/31 = "04/01 beginning cash" per statement
CASH_ANCHOR = 839.04
BENCH = {"SPY": "SPY", "QQQ": "QQQ", "IWM": "IWM", "DIA": "DIA", "COMPX": "$COMPX"}
FLOW_ACTIONS = {"Wire Received", "Funds Paid"}   # external contributions/withdrawals
DRY_RUN = "--write" not in __import__("sys").argv

# Ground-truth current positions (Schwab Positions export, 2026-06-09 01:44 ET).
EMBEDDED_POS = {
    "ANET": 1123, "AVGO": 794, "FIX": 51.7794, "GLW": 543, "GOOG": 253,
    "LLY": 198, "MU": 119, "NVDA": 463, "TPR": 600,
}
# Ground-truth transaction ledger (Schwab Transactions export, back to 2025-12-19).
# (date, action, symbol, qty, amount). Embedded so the rebuild is reproducible
# without the source CSVs (which the user removes from ~/Downloads).
EMBEDDED_TXNS = [
    ("2026-05-29", "Buy", "FIX", 51.7794, -93569.00), ("2026-05-29", "Sell", "COST", 98, 93385.20),
    ("2026-05-28", "Credit Interest", "", 0, 0.45),
    ("2026-05-19", "Buy", "NVDA", 5, -1107.85), ("2026-05-19", "Buy", "GLW", 533, -91143.00),
    ("2026-05-19", "Buy", "MU", 119, -79668.12), ("2026-05-19", "Buy", "GLW", 10, -1705.30),
    ("2026-05-15", "Qualified Dividend", "COST", 0, 144.06),
    ("2026-05-08", "Sell", "PM", 562, 95903.21), ("2026-05-08", "Sell", "GLDM", 815, 76090.75),
    ("2026-04-13", "Qualified Dividend", "PM", 0, 826.14),
    ("2026-04-01", "Qualified Dividend", "NVDA", 0, 4.58),
    ("2026-03-31", "Qualified Dividend", "AVGO", 0, 516.10),
    ("2026-03-30", "Credit Interest", "", 0, 0.53),
    ("2026-03-23", "Qualified Dividend", "TPR", 0, 240.00),
    ("2026-03-16", "Qualified Dividend", "GOOG", 0, 53.13),
    ("2026-03-03", "Buy", "PM", 1, -178.54), ("2026-03-03", "Buy", "GOOG", 253, -76595.75),
    ("2026-03-03", "Buy", "COST", 98, -99157.38), ("2026-03-03", "Buy", "PM", 561, -99969.13),
    ("2026-03-03", "Buy", "LLY", 198, -199508.76),
    ("2026-03-02", "Wire Received", "", 0, 144118.00),
    ("2026-02-27", "Wire Received", "", 0, 330052.67),
    ("2026-02-26", "Credit Interest", "", 0, 0.22),
    ("2026-02-17", "Misc Cash Entry", "", 0, 15.00), ("2026-02-17", "Service Fee", "", 0, -15.00),
    ("2026-02-17", "Funds Paid", "", 0, -180000.00),
    ("2026-02-12", "Sell", "LLY", 70, 72762.89), ("2026-02-12", "Sell", "GOOG", 258, 79791.61),
    ("2026-02-12", "Sell", "RCL", 86, 28609.60),
    ("2026-02-03", "Buy", "RCL", 86, -28209.29),
    ("2026-01-30", "Sell", "PLTR", 191, 28238.36),
    ("2026-01-21", "Buy", "GOOG", 258, -84794.28), ("2026-01-21", "Sell", "NVDA", 459, 84554.60),
    ("2026-01-12", "Buy", "LLY", 12, -12797.16), ("2026-01-12", "Buy", "TPR", 101, -13392.60),
    ("2026-01-12", "Sell", "NRG", 173, 25578.02),
    ("2025-12-31", "Qualified Dividend", "AVGO", 0, 516.10),
    ("2025-12-26", "Qualified Dividend", "NVDA", 0, 9.17),
    ("2025-12-22", "Qualified Dividend", "TPR", 0, 199.60),
    ("2025-12-19", "Buy", "LLY", 58, -62180.64), ("2025-12-19", "Sell", "PANW", 331, 62059.14),
]


def access_token():
    e = s.load_env()
    return s.refresh_access_token(s.load_tokens(), e["SCHWAB_APP_KEY"], e["SCHWAB_APP_SECRET"])["access_token"]


def load_positions():
    return dict(EMBEDDED_POS)


def load_ledger():
    trades, cash_delta, flows = [], {}, {}
    for d, action, sym, qty, amt in EMBEDDED_TXNS:
        cash_delta[d] = cash_delta.get(d, 0) + amt
        if action in FLOW_ACTIONS:
            flows[d] = flows.get(d, 0) + amt
        if action in ("Buy", "Sell") and sym:
            trades.append((d, sym, qty if action == "Buy" else -qty))
    return sorted(trades), cash_delta, flows


def cum_to(cash_delta, date):
    return sum(v for d, v in cash_delta.items() if d <= date)


def fetch_closes(at, symbols, start_date, end_date):
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int((datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400) * 1000)
    data = {}
    for key, sym in symbols.items():
        params = urllib.parse.urlencode({"periodType": "year", "frequencyType": "daily",
                                         "frequency": 1, "startDate": start_ms, "endDate": end_ms})
        hist = s.schwab_get(f"/pricehistory?symbol={urllib.parse.quote(sym)}&{params}", at, base=s.MARKET_BASE)
        prices = {}
        if isinstance(hist, dict) and "candles" in hist:
            for c in hist["candles"]:
                d = datetime.fromtimestamp(c.get("datetime", 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                prices[d] = c.get("close", 0)
        data[key] = prices
        print(f"    {key:6} {len(prices)} closes")
        time.sleep(0.3)
    return data


def main():
    history = json.loads(s.HISTORY_FILE.read_text())
    by_date = {e["date"]: e for e in history}
    live = history[-1]
    live_date = live["date"]

    pos_now = load_positions()
    trades, cash_delta, flows = load_ledger()
    base = CASH_ANCHOR - cum_to(cash_delta, CASH_ANCHOR_DATE)   # cash(D) = base + cum_to(D)

    at = access_token()
    sym_keys = {k: k for k in pos_now} | {t[1]: t[1] for t in trades}
    print(f"\nFetching closes for {len(sym_keys)} holdings + {len(BENCH)} benchmarks...")
    closes_h = fetch_closes(at, sym_keys, START_DATE, live_date)
    closes_b = fetch_closes(at, BENCH, START_DATE, live_date)

    # Verify replay reconciles to current positions.
    final = dict(pos_now)
    chk = {k: v for k, v in final.items() if abs(v) > 1e-9}
    print(f"\nReconciliation anchor = positions CSV ({len(chk)} symbols)")

    rebuild_dates = sorted(d for d in by_date if START_DATE <= d < live_date)
    prev = None
    rebuilt = []
    for d in rebuild_dates:
        pos = dict(pos_now)
        for td, sym, q in trades:
            if td > d:
                pos[sym] = round(pos.get(sym, 0) - q, 6)
        holdings, mv = [], 0.0
        for sym, qty in pos.items():
            if abs(qty) < 1e-9:
                continue
            px = closes_h.get(sym, {}).get(d)
            if px is None:
                continue
            v = round(qty * px, 2)
            mv += v
            holdings.append({"symbol": sym, "market_value": v, "weight": 0, "quantity": qty})
        cash = round(base + cum_to(cash_delta, d), 2)
        total = round(mv + cash, 2)
        for h in holdings:
            h["weight"] = round(h["market_value"] / total, 4) if total else 0
        bench = {k: round(closes_b[k][d], 2) for k in BENCH if d in closes_b.get(k, {})}
        nf = round(flows.get(d, 0), 2)
        entry = {
            "date": d, "total_value": total, "total_equity": total, "cash_balance": cash,
            "net_flows": nf, "day_gain": round(total - prev, 2) if prev is not None else 0,
            "positions_count": len(holdings), "holdings": holdings, "benchmark_prices": bench,
        }
        rebuilt.append(entry)
        prev = total

    # Backfill COMPX onto the live entry too (so the comp reaches today).
    if "COMPX" in closes_b and live_date in closes_b["COMPX"]:
        live.setdefault("benchmark_prices", {})["COMPX"] = round(closes_b["COMPX"][live_date], 2)

    # ---- validation ----
    rb = {e["date"]: e for e in rebuilt}
    def val(d): return rb[d]["total_value"] if d in rb else None
    print("\nValidation vs statements/Schwab (start-of-day = prior close):")
    print(f"  Mar 31 close: ${val('2026-03-31'):,.2f}  (stmt Apr 1 begin $1,069,816.73)")
    print(f"  Apr 30 close: ${val('2026-04-30'):,.2f}  (stmt Apr 30 end  $1,253,831.02)")
    print(f"  Mar 6 close:  ${val('2026-03-06'):,.2f}  (Schwab 'Mar 9 begin' $1,127,840.78)")
    nf3 = sum(e['net_flows'] for e in rebuilt if '2026-03-09' <= e['date'] <= '2026-06-08')
    print(f"  net_flows Mar9-Jun8: ${nf3:,.2f}  (Schwab $0)")
    nfytd = sum(e['net_flows'] for e in rebuilt if e['date'] >= '2026-01-01')
    print(f"  net_flows YTD: ${nfytd:,.2f}  (expect wires: +330,052.67 +144,118 -180,000 = +294,170.67)")
    print(f"  seam: old {by_date.get(min(rebuild_dates))['date']} was ${by_date[min(rebuild_dates)]['total_value']:,.0f} -> rebuilt ${rebuilt[0]['total_value']:,.0f}")

    if DRY_RUN:
        print(f"\nDRY RUN — would rebuild {len(rebuilt)} entries [{rebuild_dates[0]}..{rebuild_dates[-1]}]. Use --write.")
        return

    s.HISTORY_FILE.with_suffix(".json.bak").write_text(s.HISTORY_FILE.read_text())
    kept = [e for e in history if e["date"] < START_DATE or e["date"] >= live_date]
    new_hist = kept + rebuilt
    new_hist.sort(key=lambda e: e["date"])
    s.HISTORY_FILE.write_text(json.dumps(new_hist, indent=2))
    print(f"\nWrote {len(new_hist)} entries. Backup at portfolio_history.json.bak")


if __name__ == "__main__":
    main()
