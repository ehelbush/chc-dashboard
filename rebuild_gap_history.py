#!/usr/bin/env python3
"""Rebuild portfolio_history.json gap entries from actual trades (accurate backfill).

The default backfill (`backfill_missing_days`) prices the *last basket* forward
across a gap, which is wrong whenever positions change mid-gap. This script
reconstructs the TRUE daily holdings by replaying the gap's trade log from a
known-good anchor entry, re-prices each day, and overwrites the approximate
entries in place.

Holdings are exact (anchor + replayed trades reconciles to current positions).
Cash is linearly interpolated between the anchor and live entries (it's <0.3% of
NAV and external flows/dividends aren't in TRADE data) and net_flows is set to 0
for rebuilt days — those become exact once the daily-holdings file is ingested.

One-off correction for the 2026 Apr 3 -> Jun 9 freeze. ANCHOR_DATE is the last
real entry before the gap; the live (last) entry's holdings are kept and only its
net_flows is recomputed against the corrected prior day.
"""
import json
import time
import urllib.parse
from datetime import datetime, timezone

import schwab_sync as s

ANCHOR_DATE = "2026-04-03"   # last real entry before the freeze
DRY_RUN = "--write" not in __import__("sys").argv  # default: print only


def access_token():
    env = s.load_env()
    toks = s.refresh_access_token(s.load_tokens(), env["SCHWAB_APP_KEY"], env["SCHWAB_APP_SECRET"])
    return toks["access_token"]


def gap_trades(at):
    """Return [(date, symbol, signed_qty, net_amount)] for non-currency trades."""
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
            sym = ins.get("symbol")
            if sym and it.get("amount"):
                out.append((d, sym, it["amount"], t.get("netAmount", 0)))
    return sorted(out)


def fetch_closes(at, symbols, start_date, end_date):
    """{symbol: {date: close}} daily closes over [start, end]."""
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int((datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400) * 1000)
    data = {}
    for sym in symbols:
        params = urllib.parse.urlencode({
            "periodType": "month", "frequencyType": "daily", "frequency": 1,
            "startDate": start_ms, "endDate": end_ms,
        })
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


def main():
    history = json.loads(s.HISTORY_FILE.read_text())
    by_date = {e["date"]: e for e in history}
    anchor = by_date[ANCHOR_DATE]
    live = history[-1]
    live_date = live["date"]
    print(f"Anchor: {ANCHOR_DATE} (${anchor['total_value']:,.0f}) -> live: {live_date} (${live['total_value']:,.0f})")

    at = access_token()
    trades = gap_trades(at)
    print(f"\nGap trades ({len(trades)}):")
    for d, sym, q, na in trades:
        print(f"  {d}  {sym:6} qty={q:>9}  cash={na:>12,.2f}")

    # Anchor positions, then symbols we ever need prices for.
    pos0 = {h["symbol"]: h["quantity"] for h in anchor.get("holdings", [])}
    bench_syms = list(anchor.get("benchmark_prices", {}).keys()) or ["SPY", "QQQ"]
    symbols = sorted(set(pos0) | {t[1] for t in trades} | set(bench_syms))
    print(f"\nFetching closes for {len(symbols)} symbols...")
    closes = fetch_closes(at, symbols, ANCHOR_DATE, live_date)

    # Verify replay reconciles to the live holdings.
    final = dict(pos0)
    for _, sym, q, _ in trades:
        final[sym] = round(final.get(sym, 0) + q, 6)
    final = {k: v for k, v in final.items() if abs(v) > 1e-9}
    live_pos = {h["symbol"]: h["quantity"] for h in live.get("holdings", [])}
    mismatch = {k: (final.get(k), live_pos.get(k)) for k in set(final) | set(live_pos)
                if abs(final.get(k, 0) - live_pos.get(k, 0)) > 1e-4}
    print(f"\nReplay vs live holdings: {'MATCH' if not mismatch else 'MISMATCH ' + str(mismatch)}")
    if mismatch:
        print("Aborting — replay does not reconcile; do not write.")
        return

    # Dates to rebuild: existing history dates strictly inside (anchor, live).
    rebuild_dates = sorted(d for d in by_date if ANCHOR_DATE < d < live_date)
    cash0, cash1 = anchor.get("cash_balance", 0), live.get("cash_balance", 0)
    span = max(1, (datetime.strptime(live_date, "%Y-%m-%d") - datetime.strptime(ANCHOR_DATE, "%Y-%m-%d")).days)

    prev_val = anchor["total_value"]
    rebuilt = []
    for d in rebuild_dates:
        # Positions effective on day d = anchor + trades with tradeDate <= d.
        pos = dict(pos0)
        for td, sym, q, _ in trades:
            if td <= d:
                pos[sym] = round(pos.get(sym, 0) + q, 6)
        holdings, mv_total, missing = [], 0.0, []
        for sym, qty in pos.items():
            if abs(qty) < 1e-9:
                continue
            px = closes.get(sym, {}).get(d)
            if px is None:
                missing.append(sym)
                continue
            mv = round(qty * px, 2)
            mv_total += mv
            holdings.append({"symbol": sym, "market_value": mv, "weight": 0, "quantity": qty})
        cash = round(cash0 + (cash1 - cash0) * ((datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(ANCHOR_DATE, "%Y-%m-%d")).days) / span, 2)
        total = round(mv_total + cash, 2)
        for hd in holdings:
            hd["weight"] = round(hd["market_value"] / total, 4) if total else 0
        bench = {b: round(closes[b][d], 2) for b in bench_syms if d in closes.get(b, {})}
        entry = {
            "date": d, "total_value": total, "total_equity": total,
            "cash_balance": cash, "net_flows": 0,
            "day_gain": round(total - prev_val, 2), "positions_count": len(holdings),
            "holdings": holdings, "benchmark_prices": bench,
        }
        if missing:
            entry["_rebuild_missing_prices"] = missing
        rebuilt.append(entry)
        prev_val = total

    # Clear the live entry's net_flows: it was a backfill artifact (computed
    # against the wrong prior-day value). TRADE data has no external-flow info,
    # so 0 is the honest value until the daily-holdings file (Part B) sets it.
    live["net_flows"] = 0

    print(f"\nRebuilt {len(rebuilt)} entries. Sample:")
    for e in rebuilt[:3] + rebuilt[-3:]:
        print(f"  {e['date']}  val=${e['total_value']:>12,.0f}  day_gain=${e['day_gain']:>10,.0f}  pos={e['positions_count']}")
    print(f"  {live_date} (live) net_flows recomputed -> ${live['net_flows']:,.2f} (was the bogus value)")

    if DRY_RUN:
        print("\nDRY RUN — no file written. Re-run with --write to apply.")
        return

    backup = s.HISTORY_FILE.with_suffix(".json.bak")
    backup.write_text(s.HISTORY_FILE.read_text())
    new_hist = [e for e in history if not (ANCHOR_DATE < e["date"] < live_date)]
    new_hist.extend(rebuilt)
    new_hist.sort(key=lambda e: e["date"])
    s.HISTORY_FILE.write_text(json.dumps(new_hist, indent=2))
    print(f"\nWrote {len(new_hist)} entries. Backup at {backup.name}")


if __name__ == "__main__":
    main()
