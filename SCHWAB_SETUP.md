# Schwab API Integration — Setup Guide

## Prerequisites
- Charles Schwab brokerage account
- Schwab Developer status (https://developer.schwab.com)
- Python 3.10+ on your Mac

## Step 1: Register Your App on Schwab

1. Go to https://developer.schwab.com and sign in
2. Navigate to **My Apps** → **Create App**
3. Set the **Callback URL** to: `https://127.0.0.1:8182`
4. Request both scopes:
   - **Accounts and Trading Production**
   - **Market Data Production**
5. Note your **App Key** (Client ID) and **App Secret**

> Schwab may take 1-2 business days to approve your app after creation.

## Step 2: Configure Credentials

```bash
cd chc-dashboard-web
cp .env.example .env
```

Edit `.env` with your credentials:
```
SCHWAB_APP_KEY="your-app-key"
SCHWAB_APP_SECRET="your-app-secret"
SCHWAB_CALLBACK_URL="https://127.0.0.1:8182"
```

## Step 3: Authenticate

```bash
python3 schwab_auth.py
```

This will:
- Open your browser to Schwab's login page
- You log in and click "Allow"
- The script captures the authorization code and exchanges it for tokens
- Tokens are saved to `schwab_tokens.json` (gitignored)

Check token status anytime:
```bash
python3 schwab_auth.py --status
```

## Step 4: Sync Your Data

```bash
python3 schwab_sync.py
```

This fetches:
- All account balances and positions
- Current quotes for your holdings
- Benchmark data (SPY, QQQ, IWM, DIA)
- Transaction history (last 90 days)
- Sector allocation breakdown

Data is cached to `data/schwab_cache.json`.

## Step 5: Deploy to Dashboard

```bash
git add data/schwab_cache.json
git commit -m "Sync Schwab account data"
git push
```

Vercel will auto-deploy and the new **Account** tab will show your live data.

## Ongoing Maintenance

### Token Refresh (automatic)
Access tokens expire every 30 minutes. The sync script auto-refreshes them.

### Weekly Re-auth (manual, ~15 seconds)
Schwab refresh tokens expire after 7 days. You need to re-authenticate:

```bash
python3 schwab_auth.py
python3 schwab_sync.py
git add data/schwab_cache.json && git commit -m "Schwab sync" && git push
```

The dashboard shows a warning banner when re-auth is needed.

### When Tokens Expire
The dashboard **does not break**. It falls back to the last cached data and shows
a "Using cached data" banner with the last sync timestamp.

## File Overview

| File | Purpose |
|------|---------|
| `schwab_auth.py` | OAuth flow — run on Mac to authenticate |
| `schwab_sync.py` | Fetches all data and caches to JSON |
| `api/schwab.py` | Vercel serverless function serving cached data |
| `data/schwab_cache.json` | Cached account data (committed to repo) |
| `.env` | Your credentials (gitignored, never committed) |
| `schwab_tokens.json` | OAuth tokens (gitignored, never committed) |

## Security Notes

- `.env` and `schwab_tokens.json` are in `.gitignore` — they never leave your Mac
- `schwab_cache.json` contains masked account numbers (only last 4 digits)
- The Vercel endpoint strips any remaining sensitive fields before serving
- Your GitHub repo should be **private** since it contains portfolio data
