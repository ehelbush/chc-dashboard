#!/usr/bin/env python3
"""Automated Schwab re-auth wrapper — run by launchd on weekday mornings.

Schwab's refresh token is hard-capped at 7 days and cannot be renewed without
an interactive browser login (credentials + MFA). This wrapper automates
everything *around* that login so the only manual step is clicking "Allow":

  1. Checks how many days the current refresh token has left.
  2. If it's still comfortably valid, exits silently (no browser).
  3. If it's near expiry, runs schwab_auth.py (browser opens, you log in),
     then syncs the account, pushes the fresh token to the GitHub secret,
     and commits + pushes the refreshed data.

Scheduled by ~/Library/LaunchAgents/com.cherryhead.schwab-reauth.plist.

Tune REAUTH_THRESHOLD_DAYS for a wider safety margin: 3 re-auths roughly once
a week (weekday-only runs mean a rare lapse could span a weekend — the
GitHub staleness gate will flag it); 4 guarantees no lapse across long
weekends at the cost of slightly more frequent logins.
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
TOKEN_FILE = PROJECT_DIR / "schwab_tokens.json"
LOG_FILE = PROJECT_DIR / "logs" / "schwab_reauth.log"

REAUTH_THRESHOLD_DAYS = 3      # re-auth when the refresh token has <= this many days left
AUTH_TIMEOUT_SECONDS = 600     # hard cap so a missed login can't hang launchd


def log(msg):
    LOG_FILE.parent.mkdir(exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def notify(text):
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{text}" with title "CHC Dashboard re-auth"'],
        capture_output=True,
    )


def refresh_days_left():
    """Days remaining on the refresh token; -1 if the file is missing/broken."""
    try:
        t = json.loads(TOKEN_FILE.read_text())
        return (t.get("refresh_expires_at", 0) - time.time()) / 86400
    except Exception:
        return -1


def run(cmd, timeout=None, stdin=None):
    return subprocess.run(cmd, cwd=PROJECT_DIR, timeout=timeout, stdin=stdin)


def main():
    remaining = refresh_days_left()
    log(f"refresh token remaining={remaining:.2f} days (threshold={REAUTH_THRESHOLD_DAYS})")
    if remaining > REAUTH_THRESHOLD_DAYS:
        log("Token still fresh; nothing to do.")
        return 0

    notify("Opening Schwab login to refresh the 7-day token.")
    log("Starting interactive re-auth (browser will open)...")
    try:
        r = run([sys.executable, "schwab_auth.py"], timeout=AUTH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        log(f"Re-auth timed out (no login within {AUTH_TIMEOUT_SECONDS}s). Will retry next run.")
        notify("Re-auth timed out — no login. Will retry next run.")
        return 1
    if r.returncode != 0:
        log("schwab_auth.py exited non-zero. Aborting.")
        notify("Re-auth failed — see log.")
        return 1

    # Guard: confirm we actually got a fresh token before doing anything else.
    if refresh_days_left() <= 5:
        log("Token does not look refreshed after auth; aborting before sync/push.")
        notify("Re-auth did not produce a fresh token — aborting.")
        return 1

    log("Re-auth OK. Syncing account + backfilling history...")
    run([sys.executable, "schwab_sync.py"])

    log("Pushing fresh token to GitHub secret...")
    try:
        with open(TOKEN_FILE, "rb") as f:
            run(["gh", "secret", "set", "SCHWAB_TOKENS"], timeout=60, stdin=f)
    except Exception as e:
        log(f"gh secret set failed ({e}) — check `gh auth status`.")

    log("Committing refreshed data...")
    run(["git", "add", "data/schwab_cache.json", "data/portfolio_history.json"])
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_DIR)
    if staged.returncode != 0:  # there are staged changes
        run(["git", "commit", "-m", f"Schwab re-auth + sync {datetime.now():%Y-%m-%d}"])
        # CI commits a daily sync, so by the time we push, origin/main has almost
        # always moved ahead and a plain push is rejected non-fast-forward. That
        # used to silently strand the fresh data locally while the live site kept
        # serving CI's stale needs_reauth cache. Rebase onto origin first, and on
        # conflict prefer our just-synced data: in a rebase, "-X theirs" keeps the
        # commit being replayed (ours), so the live token/cache always wins over
        # CI's expired-token snapshot.
        run(["git", "fetch", "origin"])
        rebased = run(["git", "rebase", "-X", "theirs", "origin/main"])
        if rebased.returncode != 0:
            run(["git", "rebase", "--abort"])
            log("Rebase onto origin/main failed — leaving commit unpushed.")
            notify("Re-auth synced but auto-push failed — run `git push` manually.")
            return 1
        pushed = run(["git", "push"])
        if pushed.returncode == 0:
            log("Pushed.")
        else:
            log("git push failed even after rebase — see log.")
            notify("Re-auth synced but push failed — run `git push` manually.")
            return 1
    else:
        log("No data changes to commit.")

    notify("Schwab re-auth complete — data synced.")
    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
