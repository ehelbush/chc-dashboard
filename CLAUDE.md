# CHC Dashboard Web — Claude Handoff

## Project Overview
CherryHead Capital Trading Model Dashboard — a single-file React app (`index.html`) with Babel standalone, deployed on Vercel. Tracks portfolio performance, analyzes individual tickers with a proprietary timing model, and builds optimized portfolios.

**Live URL**: https://chc-dashboard-eight.vercel.app/
**Repo**: https://github.com/ehelbush/chc-dashboard

## Architecture
- **Frontend**: `index.html` — single-file React 18 + Babel standalone (~2,000 lines)
- **Backend**: Vercel serverless functions (`api/yahoo.py`, `api/schwab.py`, `api/portfolio_history.py`)
- **Data**: `data/market_screener.json` (6,000+ tickers), `data/schwab_cache.json` (live account), `data/portfolio_history.json` (daily NAV history since 2019), `data/ticker_params.json` (per-asset model params for 25 tickers), `data/tickers.json` (OHLCV for 25 tickers)
- **CI/CD**: `.github/workflows/update-screener.yml` — daily at 10 PM ET, runs Schwab sync + market screener
- **Secrets**: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_TOKENS`, `GH_PAT` in GitHub Actions

## Tab Structure (current)
1. **Performance** — CHC share price chart (NAV index), account balance, drawdown, monthly returns heatmap, strategy era performance, holdings, sector allocation
2. **Analysis** — Ticker input ribbon with all model params, Analyze + Optimize buttons, TickerDetail view with growth chart and metrics
3. **Select Assets** — 25 portfolio tickers table (enriched from screener data)
4. **Asset Screener** — 6,000+ tickers with filters (sector, market cap, recovery, returns)
5. **Portfolio Builder** — Auto-select optimal buy-and-hold portfolio with backtesting vs SPY
6. **Definitions** — Glossary of all model terms
7. **Changelog** — Release history

## CHC Trading Model
```
Combined Signal = (volPriceMix × Volume Ratio) + ((1 - volPriceMix) × Price Slope)
```

**Parameters per ticker** (stored in `data/ticker_params.json`):
- `vol_flag` (0-3): MA window for volume ratio (0=1d, 1=50d, 2=100d, 3=120d)
- `price_flag` (0-3): MA window for price slope
- `vol_price_mix` (0-1): blend weight between volume and price signals
- `buy_threshold`: signal level to trigger Buy
- `sell_threshold`: signal level to trigger Sell (currently always = buy_threshold, symmetric)

**Key functions**: `computeCHCModel()` (JS, line ~136), `compute_chc_model()` (Python, `fetch_all_tickers.py`)

## Current State — What Needs Doing Next

### Priority 1: Improve the Optimizer
The current optimizer (`optimizeTicker` function in `index.html`) does a brute-force grid search over ~13,776 param combos. It works but needs these improvements:

1. **Train/test split** — Optimize on first 80% of data, show out-of-sample performance on last 20%. This prevents overfitting. Show both in-sample and out-of-sample metrics in the results.

2. **Two-stage search** — Current grid is too narrow for thresholds (-0.02 to +0.02 misses TPR at -0.065).
   - Stage 1: Coarse pass with wide range (-0.1 to +0.1 threshold, 0.005 step; 0-1 mix, 0.1 step)
   - Stage 2: Fine pass around top 10 results (±0.01 threshold, 0.0005 step; ±0.1 mix, 0.02 step)

3. **Configurable recovery constraint** — Add input to ribbon for max recovery period (default 5 years). Currently hardcoded.

4. **Param history** — When saving optimized params, store `last_optimized` timestamp and `prev_params` so you can see what changed and when.

### Priority 2: Param Management API + Tab
1. **API endpoint** (`api/save_params.py`) — Vercel serverless function that updates `data/ticker_params.json` in the GitHub repo via the GitHub API using the `GH_PAT` secret. Should accept a JSON body with the full params object.

2. **Commit/Revert buttons** on Analysis tab:
   - After optimizing, params are "staged" (applied to ribbon but not saved)
   - **Commit** button calls the API to persist
   - **Revert** button restores last committed params from `ticker_params.json`

3. **Params tab** — Table showing all tickers with committed params. Columns: ticker, vol_flag, price_flag, mix, threshold, last_optimized, avg_yr_return, recovery_period.
   - **Optimize All** button — queues optimization for every ticker, shows progress
   - **Commit All** button — saves all staged params in one API call
   - Individual row actions: Optimize, Commit, Revert

### Priority 3: Screener params alignment
The daily screener (`fetch_all_tickers.py`) already uses `ticker_params.json` for the 25 portfolio tickers. When params are updated via the API, the next daily run will use them automatically.

## Open Questions
- **Asymmetric thresholds**: Currently buy_threshold always equals sell_threshold. Need to follow up with Dan (Emily's dad) on whether allowing different buy/sell thresholds is worth the expanded search space.
- **Schwab token refresh**: Tokens expire every 7 days. The CI workflow auto-refreshes them, but manual re-auth (`python3 schwab_auth.py`) is needed if they fully expire.

## Key File Locations
- `index.html` — entire frontend (~2,000 lines)
- `data/ticker_params.json` — per-asset model parameters
- `data/market_screener.json` — daily screener results for 6,000+ tickers
- `data/schwab_cache.json` — live Schwab account data
- `data/portfolio_history.json` — daily NAV history (1,895+ entries)
- `schwab_sync.py` — Schwab API sync with backfill
- `fetch_all_tickers.py` — batch screener with per-asset params
- `.github/workflows/update-screener.yml` — daily CI workflow
- `api/yahoo.py` — Yahoo Finance proxy for live price data

## Working in This Repo
- Push to `main` triggers Vercel deploy (~30 seconds)
- `index.html` uses Babel standalone — avoid `<` in JSX expressions (use `!==` or `>=` instead), and keep special unicode characters in constants outside JSX
- The file is large (~2,000 lines) — use line number references from Grep
- Git worktree at `.claude/worktrees/quirky-williamson` is the active working branch
