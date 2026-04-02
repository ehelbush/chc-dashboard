# CHC Dashboard Web — Claude Handoff

## Project Overview
CherryHead Capital Trading Model Dashboard — a single-file React app (`index.html`) with Babel standalone, deployed on Vercel. Tracks portfolio performance, analyzes individual tickers with a proprietary timing model, and builds optimized portfolios.

**Live URL**: https://chc-dashboard-eight.vercel.app/
**Repo**: https://github.com/ehelbush/chc-dashboard
**Current version**: v5.3.0

## Architecture
- **Frontend**: `index.html` — single-file React 18 + Babel standalone (~3,100 lines)
- **Backend**: Vercel serverless functions (`api/yahoo.py`, `api/schwab.py`, `api/portfolio_history.py`, `api/save_params.py`, `api/yahoo_profile.py`, `api/yahoo_quotes.py`)
- **Data**: `data/market_screener.json` (6,000+ tickers), `data/schwab_cache.json` (live account), `data/portfolio_history.json` (daily NAV history since 2019, 1,898 entries), `data/ticker_params.json` (per-asset model params for 25 tickers), `data/tickers.json` (OHLCV for 25 tickers)
- **CI/CD**: `.github/workflows/update-screener.yml` — weekdays at 10 PM ET, runs Schwab sync + market screener + token refresh
- **Secrets (GitHub Actions)**: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_TOKENS`, `GH_PAT`
- **Secrets (Vercel)**: `GH_PAT` (for save_params API)

## Tab Structure (current)
1. **Performance** — NAV chart, P&L cards, toggleable benchmarks (SPY/QQQ/IWM/DIA), drawdown, monthly returns heatmap, strategy eras, holdings with CSV export, sector allocation, concentration metrics, Refresh Prices button
2. **Analysis** — Optimize (primary) and Analyze sections, company fundamentals, financials, analyst consensus, news, signal chart, drawdown chart, trade statistics, trade log with CSV export
3. **Select Assets** — 25 portfolio tickers table with data date indicator
4. **Asset Screener** — 6,000+ tickers with filter dropdowns, presets, page jump, CSV export
5. **Portfolio Builder** — Auto-select optimal buy-and-hold portfolio from screener with guardrails (max assets, max recovery, min market cap, sector, signal), backtests vs SPY
6. **Params** — All tickers with params, train/test metrics, Optimize All, Commit All, Portfolio Opt, export/import
7. **Definitions** — Searchable glossary of all model terms
8. **Changelog** — Release history

## CHC Trading Model
```
Combined Signal = (volPriceMix × Volume Ratio) + ((1 - volPriceMix) × Price Slope)
```

**Parameters per ticker** (stored in `data/ticker_params.json`):
- `vol_flag` (0-3): MA window for volume ratio (0=1d, 1=50d, 2=100d, 3=120d)
- `price_flag` (0-3): MA window for price slope
- `vol_price_mix` (0-1): blend weight between volume and price signals
- `buy_threshold`: signal level to trigger Buy
- `sell_threshold`: signal level to trigger Sell (can be asymmetric)

**Key functions**: `computeCHCModel()` (JS, line ~136), `compute_chc_model()` (Python, `fetch_all_tickers.py`)

## What's Been Done (completed this session)
- **v4.4–4.7**: Optimizer improvements (two-stage search, train/test split, walk-forward validation, asymmetric thresholds, portfolio-level optimization)
- **v4.4–4.6**: Params tab, save_params API, commit/revert workflow, export/import
- **v4.8**: Sector allocation fix, day gain % fix, holdings improvements
- **v4.9**: P&L cards, toggleable benchmarks, concentration metrics, trade coloring
- **v5.0**: Mobile responsive, tooltips, screener presets, portfolio builder error handling
- **v5.1**: Dark/light mode, definition search, breadcrumbs, CSV export, data dates
- **v5.2**: Company fundamentals, financials, analyst consensus, news (yahoo_profile.py)
- **v5.3**: Signal chart, drawdown chart, trade statistics, trade log
- **Refresh Prices**: Live Yahoo quotes button on Performance tab (yahoo_quotes.py)
- **Schwab sync fix**: Auth script fixed (urllib SSL bypass), daily workflow now running, all secrets configured
- **Blank page fix**: Extra `};` in runOptimizer that broke Babel compilation

## Current State — What Needs Doing Next

### Priority 1: GH_PAT in Vercel
The `GH_PAT` has been added to Vercel environment variables. The Commit button on the Analysis tab should now work for saving optimized params. **Verify this works** by optimizing a ticker and clicking Commit.

### Priority 2: Portfolio Builder Enhancements
The Portfolio Builder auto-selects from 6,000+ tickers with buy-and-hold backtesting. Potential improvements from team discussion:
1. **Traded portfolio mode (v2)** — Currently buy-and-hold only. A future version could apply the CHC timing model to each asset in the portfolio, but adds complexity (tax implications, reallocation logic). Team agreed to crawl before walking.
2. **Compare vs current portfolio** — Show how the auto-built portfolio compares to the actual Schwab holdings. Helps "defend" current selections.
3. **Sector diversification constraint** — Prevent the builder from over-concentrating in one sector.

### Priority 3: Real-time Price Refresh
The Refresh Prices button is built but could be enhanced:
1. **Auto-refresh during market hours** — Optional polling every 60s when market is open
2. **Refresh on tab focus** — Fetch new prices when user switches back to the dashboard

### Priority 4: Schwab Token Monitoring
- Tokens expire every 7 days. The daily workflow auto-refreshes them.
- If the workflow fails for a full week, manual re-auth is needed: `python3 schwab_auth.py` (requires browser)
- The dashboard shows a warning banner when the token is near expiry

### Other Ideas
- **Asymmetric thresholds**: Implemented and available via checkbox. Team should evaluate whether the added search space is worth it.
- **Volume up/down parameter**: Dan mentioned an additional parameter beyond the current vol_flag. May need to expand the model.

## Open Questions
- **Traded portfolio builder**: Team agreed buy-and-hold first, traded v2 later. When ready, need to handle tax implications and fund reallocation between assets.
- **Schwab re-auth**: If tokens fully expire, someone needs to run `schwab_auth.py` locally with a browser. Consider adding a Slack alert when the workflow detects expiring tokens.

## Key File Locations
- `index.html` — entire frontend (~3,100 lines)
- `data/ticker_params.json` — per-asset model parameters
- `data/market_screener.json` — daily screener results for 6,000+ tickers
- `data/schwab_cache.json` — live Schwab account data
- `data/portfolio_history.json` — daily NAV history (1,898 entries)
- `schwab_sync.py` — Schwab API sync with backfill
- `schwab_auth.py` — Schwab OAuth browser auth flow
- `fetch_all_tickers.py` — batch screener with per-asset params
- `.github/workflows/update-screener.yml` — daily CI workflow
- `api/yahoo.py` — Yahoo Finance proxy for OHLCV data
- `api/yahoo_profile.py` — Yahoo Finance company fundamentals + news
- `api/yahoo_quotes.py` — Yahoo Finance batch live quotes
- `api/save_params.py` — GitHub API writer for ticker_params.json
- `api/schwab.py` — serves cached Schwab data
- `vercel.json` — API route rewrites

## Working in This Repo
- Push to `main` triggers Vercel deploy (~30 seconds)
- `index.html` uses Babel standalone — avoid `<` in JSX expressions (use `!==` or `>=` instead), and keep special unicode characters in constants outside JSX
- The file is large (~3,100 lines) — use line number references from Grep
- Use `@babel/core` + `@babel/preset-react` locally to syntax-check before pushing: catches Babel compilation errors that would cause blank pages
- `.env` file (local only, not committed) holds `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` for local auth/sync
