# CHC Tax Position Analysis: 2026-09-04

One-off analysis of the current tax position (action item #1 from the 2026-08-28 team meeting), prompted by AVGO moving to a soft sell. Question: how much AVGO could be unloaded if we harvest the FIX unrealized loss and apply FY26 realized losses plus FY25 carryforward losses?

**Headline: essentially none of the AVGO gain can be sheltered.** Both assumed loss pools are smaller than expected:

1. FY26 realized to date is a net GAIN of about +$12.0k ST, not a loss. The GOOG (-$5.0k) and LLY (-$2.2k) losses booked 2/12/26 were wash sales (both repurchased 3/3/26, 19 days later) and are disallowed, already rolled into current basis (confirmed: Schwab reports GOOG basis 322.14 vs 302.75 raw, LLY 1018.81 vs 1007.62 raw).
2. FY25 carryforward is ~$105. CHC passed through -$84,017 ST on the filed 2025 1065, but on Eric & Emily's 2025 draft 1040 (dated 7/16/26) their -$80,404 share was absorbed by +$54,859 personal ST gains (Robinhood, Morgan Stanley) and +$22,440 LT gains, leaving net -$3,105, of which $3,000 was used against ordinary income. Carryover into 2026: ~$105 ST.

## Data sources

- Schwab transaction history 2019-2026 via API (19,198 transactions, paginated past the 3,000-record response cap), replayed FIFO with split adjustments (NVDA 10:1 2024-06, AVGO 10:1 2024-07, AAPL 4:1 2020-08, NVDA 4:1 2021-07). Reconstruction reconciles exactly to all 9 current holdings.
- `data/schwab_cache.json` synced 2026-09-03 (prices are 9/3 close).
- Filed 2025 CHC 1065 + K-1s and Eric's draft 2025 1040 (Dropbox: `Charts Copy/Adminstration/Tax Documents/CHC 2025 Tax Documents/`).

## FY26 realized to date (CHC Schwab account, through 2026-09-04)

All short-term; no long-term sales this year.

| Symbol | Realized G/L | Term | Notes |
|---|---:|---|---|
| NVDA | +19,445.59 | ST | sold 459 sh 1/21/26, lots from 6/13/25 |
| GLDM | +7,750.65 | ST | 10/17/25 to 5/8/26 |
| PLTR | +1,947.65 | ST | 6/20/25 to 1/30/26 |
| RCL | +400.33 | ST | 2/3/26 to 2/12/26 |
| GLW | -6,869.68 | ST | 5/19/26 to 8/5/26 |
| COST | -5,770.24 | ST | 3/3/26 to 5/29/26 |
| PM | -4,242.37 | ST | 3/3/26 to 5/8/26 |
| NRG | -674.70 | ST | 6/20/25 to 1/12/26 |
| **Net allowed** | **+11,987.23** | ST | |
| GOOG | (-5,002.62) | ST | WASH SALE, disallowed (rebought 3/3/26) |
| LLY | (-2,214.90) | ST | WASH SALE, disallowed (rebought 3/3/26) |

## FY25 (filed 2025 returns)

| Item | ST | LT |
|---|---:|---:|
| CHC 1065 Schedule D net | -84,017 | +8 |
| Wash sales disallowed at LLC level (in the above) | 51,486 | |
| Eric K-1 (70.1%) | -58,896 | +6 |
| Emily K-1 (25.9%) | ~-21,508 | |
| Jerome Rasky K-1 (2.0%) | ~-1,681 | |
| Dan Rasky K-1 (2.0%) | -1,680 | |
| Eric+Emily carryover into 2026 (draft 1040) | **~-105** | 0 |

Dan's and Jerome's carryovers depend on their personal returns; at most their K-1 amounts (~$1.7k each).

## Current unrealized position (9/3 close prices)

| Position | Qty | Basis/sh | Price | Unrealized | Term |
|---|---:|---:|---:|---:|---|
| AVGO | 794 | 250.39 | 355.95 | +83,812 | 100% LT (acq 6/13/25) |
| FIX | 51.78 | 1,807.07 | 1,594.89 | -10,987 | 100% ST (acq 5/29/26) |

FIX is the only unrealized loss in the book. Every other holding (LLY, ANET, MU, NVDA, AHR, GOOG, TPR) is at a gain.

## Netting if FIX is harvested and AVGO trimmed

| Bucket | Amount |
|---|---:|
| FY26 ST realized to date | +11,987 |
| FIX harvest | -10,987 |
| FY25 carryover (Eric+Emily) | -105 |
| **Net ST before any AVGO sale** | **+895** |
| LT shelter available for AVGO | **$0** |

The ST bucket is already positive even after harvesting FIX, so every dollar of AVGO LT gain sold is taxable. AVGO trim scenarios (LT gain at $105.56/sh):

| Scenario | Shares | Proceeds | LT gain realized |
|---|---:|---:|---:|
| $40k trim (meeting discussion) | 112 | ~$39.9k | ~+11,800 |
| 25% of position | 199 | ~$70.8k | ~+21,000 |
| 50% of position | 397 | ~$141.3k | ~+41,900 |
| Full exit | 794 | ~$282.6k | ~+83,800 |

70.1% of any gain lands on Eric's return (LT preferential rates plus NIIT plus CA), 25.9% Emily, 2% each Dan and Jerome.

## Caveats

- Lot matching is FIFO; Schwab's actual lot relief may differ slightly (the LLY/GOOG wash math matched Schwab's reported basis exactly, so FY26 numbers should be close). Chris's 1099-B for 2026 governs.
- Prices are 9/3 close; AVGO moved to a soft sell since, so the gain per share may be somewhat lower now.
- If FIX is harvested, do not repurchase FIX within 30 days or the loss is disallowed (same trap as GOOG/LLY in February).
- Eric's 2025 1040 is a DRAFT (7/16/26); the ~$105 carryover could change when filed.
- This is analysis, not tax advice; confirm with Chris Moore before trading on it.
