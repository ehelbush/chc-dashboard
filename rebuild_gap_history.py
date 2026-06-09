#!/usr/bin/env python3
"""Rebuild portfolio_history.json gap entries from ground-truth account data.

The default backfill (`backfill_missing_days`) prices the *last basket* forward
across a gap, which is wrong whenever positions change mid-gap. This script
reconstructs each gap day exactly:

  - HOLDINGS: replay the gap trade log from a known-good anchor entry (reconciles
    to current positions to the share), priced per day from Schwab pricehistory.
  - CASH: reconstruct from the full transaction ledger CSV (trades + dividends +
    interest), anchored to the 04/01 statement beginning cash. This reconciles
    exactly to the 04/30 ($1,669.76) and 05/31 ($183.96) statement cash and the
    06/09 positions file ($0.16).
  - LIVE (last) entry: replaced with the ground-truth positions CSV snapshot.
  - net_flows: 0 across the gap — the transaction ledger shows no external
    deposits/withdrawals in the window (only dividends/interest, which are income).

One-off correction for the 2026 Apr 3 -> Jun 9 freeze. Dry-run by default; pass
--write to apply (writes a .json.bak first).

Source files (Schwab exports), parameterized below:
  TXN_CSV       — full transaction history CSV
  POSITIONS_CSV — current positions snapshot CSV
"""
import csv
import json
import time
import urllib.parse
from datetime import datetime, timezone

import schwab_sync as s

ANCHOR_DATE = "2026-04-03"      # last real entry before the freeze
OPENING_CASH_DATE = "2026-04-01"
OPENING_CASH = 839.04          # 04/01 beginning cash, per the April statement
TXN_CSV = "/Users/ehelbush/Downloads/Limit_Liability_Company_XXX965_Transactions_20260609-014437.csv"
POSITIONS_CSV = "/Users/ehelbush/Downloads/Limit Liability Company-Positions-2026-06-09-014450.csv"
# Statement cash checkpoints for validation (date -> cash).
CASH_CHECKPOINTS = {"2026-04-30": 1669.76, "2026-05-31": 183.96, "2026-06-09": 0.16}
DRY_RUN = "--write" not in __import__("sys").argv


def access_token():
    env = s.load_env()
    toks = s.refresh_access_token(s.load_tokens(), env["SCHWAB_APP_KEY"], env["SCHWAB_APP_SECRET"])
    return toks["access_token"]


def _money(x):
    return float(x.replace("$", "").replace(",", "")) if x and x.strip() else 0.0


def cash_series():
    """Cumulative cash by date from the ledger; returns (sorted_dates, cum_values)."""
    from collections import defaultdict
    delta = defaultdict(float)
    for r in csv.DictReader(open(TXN_CSV)):
        d = datetime.strptime(r["Date"], "%m/%d/%Y").strftime("%Y-%m-%d")
        if d >= OPENING_CASH_DATE:
            delta[d] += _money(r["Amount"])
    cash, dates, vals = OPENING_CASH, [], []
    for d in sorted(delta):
        cash = round(cash + delta[d], 2)
        dates.append(d)
        vals.append(cash)
    return dates, vals


def cash_on(date, dates, vals):
    """Cash balance as of end of `date` (carries the last change forward)."""
    cash = OPENING_CASH
    for d, v in zip(dates, vals):
        if d <= date:
            cash = v
        else:
            break
    return cash


def gap_trades(at):
    h = s.fetch_accounts(at)[0]["hashValue"]
    out = []
    for t in s.fetch_transactions(at, h, days=90):
        d = t.get("tradeDate", "")[:10]
        if d <= ANCHOR_DATE:
            continue
        for it in t.get("transferItems", []):
            ins = it.get("instrument", {})
            if ins.get("assetType") in (None, "CURRENCY", "CASH_EQUIVALENT"):
                continue
            if ins.get("symbol") and it.get("amount"):
                out.append((d, ins["symbol"], it["amount"]))
    return sorted(out)


def fetch_closes(at, symbols, start_date, end_date):
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int((datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400) * 1000)
    data = {}
    for sym in symbols:
        params = urllib.parse.urlencode({"periodType": "month", "frequencyType": "daily",
                                         "frequency": 1, "startDate": start_ms, "endDate": end_ms})
        hist = s.schwab_get(f"/pricehistory?symbol={sym}&{params}", at, base=s.MARKET_BASE)
        prices = {}
        if hist and "candles" in hist:
            for c in hist["candles"]:
                d = datetime.fromtimestamp(c.get("datetime", 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                prices[d] = c.get("close", 0)
        data[sym] = prices
        print(f"    {sym:6} {len(prices)} closes")
        time.sleep(0.3)
    return data


def live_entry_from_positions(date, prev_value):
    """Build the live (last) history entry from the ground-truth positions CSV.

    The CSV has a title line + blank line before the real header, so seek to it.
    """
    lines = open(POSITIONS_CSV, newline="").read().splitlines()
    hdr = next(i for i, ln in enumerate(lines) if ln.startswith('"Symbol"'))
    holdings, total_mv, cash = [], 0.0, 0.0
    for r in csv.DictReader(lines[hdr:]):
        sym = (r.get("Symbol") or "").strip()
        mv = _money(r.get("Mkt Val (Market Value)", "0"))
        if sym == "Cash & Cash Investments":
            cash = mv
            continue
        if r.get("Asset Type", "").strip() not in ("Equity", "ETF", "ETFs"):
            continue
        qty = _money(r.get("Qty (Quantity)", "0"))
        total_mv += mv
        holdings.append({"symbol": sym, "market_value": round(mv, 2), "weight": 0, "quantity": qty})
    total = round(total_mv + cash, 2)
    for hd in holdings:
        hd["weight"] = round(hd["market_value"] / total, 4) if total else 0
    return {
        "date": date, "total_value": total, "total_equity": total, "cash_balance": round(cash, 2),
        "net_flows": 0, "day_gain": round(total - prev_value, 2), "positions_count": len(holdings),
        "holdings": holdings,
    }


def main():
    history = json.loads(s.HISTORY_FILE.read_text())
    by_date = {e["date"]: e for e in history}
    anchor = by_date[ANCHOR_DATE]
    live_date = history[-1]["date"]
    print(f"Anchor {ANCHOR_DATE} (${anchor['total_value']:,.0f}) -> live {live_date}")

    dates, vals = cash_series()
    print("\nCash ledger checkpoints:")
    for d, expect in sorted(CASH_CHECKPOINTS.items()):
        got = cash_on(d, dates, vals)
        print(f"  {d}: ${got:,.2f} (expect ${expect:,.2f}) {'OK' if abs(got-expect)<0.05 else 'DIFF'}")

    at = access_token()
    trades = gap_trades(at)
    pos0 = {h["symbol"]: h["quantity"] for h in anchor.get("holdings", [])}
    bench_syms = list(anchor.get("benchmark_prices", {}).keys()) or ["SPY", "QQQ"]
    symbols = sorted(set(pos0) | {t[1] for t in trades} | set(bench_syms))
    print(f"\nFetching closes for {len(symbols)} symbols...")
    closes = fetch_closes(at, symbols, ANCHOR_DATE, live_date)

    # Verify replay reconciles to the positions CSV.
    final = dict(pos0)
    for _, sym, q in trades:
        final[sym] = round(final.get(sym, 0) + q, 6)
    final = {k: v for k, v in final.items() if abs(v) > 1e-9}
    live = live_entry_from_positions(live_date, anchor["total_value"])
    live_pos = {h["symbol"]: h["quantity"] for h in live["holdings"]}
    mismatch = {k: (final.get(k), live_pos.get(k)) for k in set(final) | set(live_pos)
                if abs(final.get(k, 0) - live_pos.get(k, 0)) > 1e-4}
    print(f"\nReplay vs positions CSV holdings: {'MATCH' if not mismatch else 'MISMATCH ' + str(mismatch)}")
    if mismatch:
        print("Aborting — does not reconcile.")
        return

    rebuild_dates = sorted(d for d in by_date if ANCHOR_DATE < d < live_date)
    prev_val = anchor["total_value"]
    rebuilt = []
    for d in rebuild_dates:
        pos = dict(pos0)
        for td, sym, q in trades:
            if td <= d:
                pos[sym] = round(pos.get(sym, 0) + q, 6)
        holdings, mv_total = [], 0.0
        for sym, qty in pos.items():
            if abs(qty) < 1e-9:
                continue
            px = closes.get(sym, {}).get(d)
            if px is None:
                continue
            mv = round(qty * px, 2)
            mv_total += mv
            holdings.append({"symbol": sym, "market_value": mv, "weight": 0, "quantity": qty})
        cash = cash_on(d, dates, vals)
        total = round(mv_total + cash, 2)
        for hd in holdings:
            hd["weight"] = round(hd["market_value"] / total, 4) if total else 0
        bench = {b: round(closes[b][d], 2) for b in bench_syms if d in closes.get(b, {})}
        rebuilt.append({
            "date": d, "total_value": total, "total_equity": total, "cash_balance": cash,
            "net_flows": 0, "day_gain": round(total - prev_val, 2),
            "positions_count": len(holdings), "holdings": holdings, "benchmark_prices": bench,
        })
        prev_val = total

    live["day_gain"] = round(live["total_value"] - prev_val, 2)

    print(f"\nRebuilt {len(rebuilt)} entries + live. Sample:")
    for e in rebuilt[:2] + rebuilt[-2:] + [live]:
        tag = " (live/positions)" if e is live else ""
        print(f"  {e['date']}  val=${e['total_value']:>12,.0f}  cash=${e['cash_balance']:>10,.2f}  pos={e['positions_count']}{tag}")

    if DRY_RUN:
        print("\nDRY RUN — re-run with --write to apply.")
        return

    s.HISTORY_FILE.with_suffix(".json.bak").write_text(s.HISTORY_FILE.read_text())
    new_hist = [e for e in history if not (ANCHOR_DATE < e["date"] <= live_date)]
    new_hist.extend(rebuilt)
    new_hist.append(live)
    new_hist.sort(key=lambda e: e["date"])
    s.HISTORY_FILE.write_text(json.dumps(new_hist, indent=2))
    print(f"\nWrote {len(new_hist)} entries. Backup at portfolio_history.json.bak")


if __name__ == "__main__":
    main()
