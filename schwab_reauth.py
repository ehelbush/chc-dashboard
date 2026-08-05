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
STATE_FILE = PROJECT_DIR / "logs" / "reauth_state.json"

REAUTH_THRESHOLD_DAYS = 3      # re-auth when the refresh token has <= this many days left
AUTH_TIMEOUT_SECONDS = 1800    # 30 min window to finish the browser login before
                               # the helper is killed. Too short (was 600s/10min)
                               # meant a login not finished promptly left the
                               # callback server dead, so the redirect hit a dead
                               # port and the browser showed "Unable to connect".
ESCALATE_AFTER_FAILURES = 2    # consecutive misses before a transient banner is
                               # upgraded to a modal that must be dismissed.


def log(msg):
    LOG_FILE.parent.mkdir(exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _as_quote(text):
    """Escape a Python string for embedding in an AppleScript string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(text):
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{_as_quote(text)}" with title "CHC Dashboard re-auth"'
         ' sound name "Basso"'],
        capture_output=True,
    )


def alert(text):
    """Modal dialog that stays up until dismissed.

    `display notification` is a banner that self-dismisses in a few seconds. In
    July 2026 the 8am job timed out 13 mornings running, fired 13 banners nobody
    was at the keyboard to see, and the token silently expired — the dashboard
    served three-week-old data until someone happened to check. Anything meant to
    survive an unattended morning has to persist on screen, so escalation uses an
    alert rather than another banner.

    Launched detached: `giving up after` keeps it from hanging forever, but we
    still must not block the launchd job for the full window.
    """
    script = (
        'tell application "System Events" to display alert '
        '"CHC Dashboard: Schwab re-auth needed" '
        f'message "{_as_quote(text)}" as critical giving up after 3600'
    )
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"Could not raise modal alert: {e}")


def _read_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def record_failure(reason):
    """Bump the consecutive-miss counter; return the new count."""
    n = _read_state().get("consecutive_failures", 0) + 1
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "consecutive_failures": n,
        "last_failure": datetime.now().isoformat(timespec="seconds"),
        "last_reason": reason,
    }, indent=2))
    return n


def clear_failures():
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "consecutive_failures": 0,
        "last_success": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))


def fail(reason, banner, remaining=None):
    """Log + notify a failed run, escalating to a modal when it's not a one-off.

    Escalates on the 2nd consecutive miss, or immediately once the refresh token
    is actually expired — at that point the dashboard is already serving stale
    data, so it is not a warning about the future.
    """
    log(reason)
    n = record_failure(reason)
    expired = remaining is not None and remaining <= 0
    if expired or n >= ESCALATE_AFTER_FAILURES:
        if expired:
            detail = (f"The Schwab refresh token EXPIRED {abs(remaining):.0f} day(s) ago. "
                      "The dashboard is serving stale data right now.")
        else:
            detail = f"{n} consecutive re-auth attempts have failed."
        alert(f"{detail}\n\n{reason}\n\n"
              "Fix: run `python3 schwab_reauth.py` in the repo and complete the "
              "Schwab login (credentials + MFA, then Allow).")
        log(f"Escalated to modal alert (consecutive_failures={n}, expired={expired}).")
    else:
        notify(banner)
    return 1


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
        clear_failures()
        return 0

    notify("Opening Schwab login to refresh the 7-day token.")
    log("Starting interactive re-auth (browser will open)...")
    try:
        r = run([sys.executable, "schwab_auth.py"], timeout=AUTH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return fail(
            f"Re-auth timed out (no login within {AUTH_TIMEOUT_SECONDS}s). Will retry next run.",
            "Re-auth timed out — no login. Will retry next run.",
            remaining,
        )
    if r.returncode != 0:
        return fail("schwab_auth.py exited non-zero. Aborting.",
                    "Re-auth failed — see log.", remaining)

    # Guard: confirm we actually got a fresh token before doing anything else.
    if refresh_days_left() <= 5:
        return fail("Token does not look refreshed after auth; aborting before sync/push.",
                    "Re-auth did not produce a fresh token — aborting.", remaining)

    # Auth itself succeeded, so the miss streak is broken. Later sync/push
    # problems are a different failure and raise their own notification; they
    # must not keep the "re-auth needed" counter climbing.
    clear_failures()

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
