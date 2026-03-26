#!/usr/bin/env python3
"""
Schwab OAuth Authentication Helper
===================================
Run this script on your Mac to authenticate with the Schwab API.
It opens a browser for you to log in, captures the authorization code,
exchanges it for tokens, and saves them to schwab_tokens.json.

Usage:
    1. Set your credentials in .env or pass as arguments:
       python3 schwab_auth.py --app-key YOUR_KEY --app-secret YOUR_SECRET
    2. A browser window opens — log into Schwab and authorize the app
    3. Tokens are saved to schwab_tokens.json

Re-run this script every 7 days when the refresh token expires.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TOKEN_FILE = SCRIPT_DIR / "schwab_tokens.json"
ENV_FILE = SCRIPT_DIR / ".env"

# Schwab API endpoints
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
DEFAULT_CALLBACK = "https://127.0.0.1:8182"


def load_env():
    """Load .env file if it exists."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def save_tokens(tokens):
    """Save tokens to JSON file with metadata."""
    tokens["saved_at"] = datetime.now(timezone.utc).isoformat()
    tokens["expires_at"] = datetime.now(timezone.utc).timestamp() + tokens.get("expires_in", 1800)
    tokens["refresh_expires_at"] = datetime.now(timezone.utc).timestamp() + 7 * 24 * 3600  # 7 days
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    print(f"\n  Tokens saved to {TOKEN_FILE}")
    print(f"  Access token expires in {tokens.get('expires_in', 1800) // 60} minutes")
    print(f"  Refresh token expires in 7 days")


def load_tokens():
    """Load existing tokens if available."""
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def exchange_code_for_tokens(auth_code, app_key, app_secret, callback_url):
    """Exchange authorization code for access + refresh tokens."""
    # Use requests library (same approach as Stock-Updater's working code)
    try:
        import requests
    except ImportError:
        print("  Installing requests library...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--break-system-packages", "-q"])
        import requests

    # URL-decode the auth code if it was encoded
    auth_code = urllib.parse.unquote(auth_code)

    try:
        response = requests.post(
            url=TOKEN_URL,
            auth=(app_key, app_secret),
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": callback_url,
            },
            timeout=30,
        )

        if response.ok:
            tokens = response.json()
            if "access_token" in tokens:
                return tokens
            else:
                print(f"  Error: Unexpected response: {tokens}")
                return None
        else:
            print(f"  Error exchanging code: HTTP {response.status_code}")
            print(f"  Response: {response.text[:500]}")
            return None
    except Exception as e:
        print(f"  Error exchanging code: {e}")
        return None


def refresh_access_token(app_key, app_secret):
    """Refresh the access token using the refresh token."""
    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        print("  No refresh token found. Run full auth flow.")
        return None

    # Check if refresh token is expired
    refresh_expires = tokens.get("refresh_expires_at", 0)
    if time.time() > refresh_expires:
        print("  Refresh token has expired (7-day limit). Run full auth flow.")
        return None

    creds = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            new_tokens = json.loads(resp.read().decode())
            if "access_token" in new_tokens:
                # Preserve refresh token expiry from original auth
                new_tokens["refresh_expires_at"] = tokens.get("refresh_expires_at", 0)
                save_tokens(new_tokens)
                return new_tokens
    except Exception as e:
        print(f"  Error refreshing token: {e}")

    return None


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture the OAuth callback."""
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]

        if code:
            CallbackHandler.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family:system-ui;text-align:center;padding:60px;background:#0f1117;color:#e4e6ed">
            <h1 style="color:#22c55e">Authorization Successful!</h1>
            <p>You can close this window and return to the terminal.</p>
            </body></html>
            """)
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Error: No authorization code received</h1></body></html>")

    def log_message(self, format, *args):
        pass  # Suppress HTTP log noise


def generate_self_signed_cert():
    """Generate a temporary self-signed cert for the HTTPS callback server."""
    import subprocess
    import tempfile

    cert_dir = Path(tempfile.mkdtemp())
    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"

    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key_file), "-out", str(cert_file),
        "-days", "1", "-nodes",
        "-subj", "/CN=127.0.0.1"
    ], capture_output=True, check=True)

    return str(cert_file), str(key_file)


def run_auth_flow(app_key, app_secret, callback_url):
    """Run the full OAuth authorization flow."""
    # Parse callback URL to get port
    parsed = urllib.parse.urlparse(callback_url)
    port = parsed.port or 8182

    # Build authorization URL
    auth_params = urllib.parse.urlencode({
        "client_id": app_key,
        "redirect_uri": callback_url,
        "response_type": "code",
    })
    full_auth_url = f"{AUTH_URL}?{auth_params}"

    print(f"\n  Opening browser for Schwab authorization...")
    print(f"  If the browser doesn't open, visit this URL:\n")
    print(f"  {full_auth_url}\n")

    # Generate self-signed cert for HTTPS callback
    try:
        cert_file, key_file = generate_self_signed_cert()
    except Exception as e:
        print(f"  Warning: Could not generate SSL cert ({e})")
        print(f"  Falling back to manual code entry.")
        webbrowser.open(full_auth_url)
        print(f"\n  After authorizing, paste the FULL callback URL here:")
        callback = input("  > ").strip()
        parsed_cb = urllib.parse.urlparse(callback)
        params = urllib.parse.parse_qs(parsed_cb.query)
        code = params.get("code", [None])[0]
        if code:
            return exchange_code_for_tokens(code, app_key, app_secret, callback_url)
        else:
            print("  Error: Could not extract authorization code from URL")
            return None

    # Start HTTPS callback server
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    # Open browser
    webbrowser.open(full_auth_url)

    print(f"  Waiting for authorization callback on port {port}...")
    print(f"  (Log into Schwab and click 'Allow')\n")

    # Wait for callback (timeout after 5 minutes)
    server.timeout = 300
    while CallbackHandler.auth_code is None:
        server.handle_request()

    server.server_close()

    if CallbackHandler.auth_code:
        print(f"  Authorization code received!")
        tokens = exchange_code_for_tokens(
            CallbackHandler.auth_code, app_key, app_secret, callback_url
        )
        if tokens:
            save_tokens(tokens)
            return tokens

    return None


def main():
    parser = argparse.ArgumentParser(description="Schwab OAuth Authentication")
    parser.add_argument("--app-key", help="Schwab App Key (Client ID)")
    parser.add_argument("--app-secret", help="Schwab App Secret")
    parser.add_argument("--callback-url", default=DEFAULT_CALLBACK, help="OAuth callback URL")
    parser.add_argument("--refresh", action="store_true", help="Just refresh the access token")
    parser.add_argument("--status", action="store_true", help="Check current token status")
    args = parser.parse_args()

    # Load from .env if not provided as args
    env = load_env()
    app_key = args.app_key or env.get("SCHWAB_APP_KEY") or os.environ.get("SCHWAB_APP_KEY")
    app_secret = args.app_secret or env.get("SCHWAB_APP_SECRET") or os.environ.get("SCHWAB_APP_SECRET")
    callback_url = args.callback_url or env.get("SCHWAB_CALLBACK_URL") or DEFAULT_CALLBACK

    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║   CherryHead Capital — Schwab API Auth       ║")
    print("  ╚══════════════════════════════════════════════╝")

    # Status check
    if args.status:
        tokens = load_tokens()
        if not tokens:
            print("\n  No tokens found. Run auth flow first.")
        else:
            now = time.time()
            access_ok = now < tokens.get("expires_at", 0)
            refresh_ok = now < tokens.get("refresh_expires_at", 0)
            refresh_days = max(0, (tokens.get("refresh_expires_at", 0) - now) / 86400)
            print(f"\n  Access Token:  {'VALID' if access_ok else 'EXPIRED'}")
            print(f"  Refresh Token: {'VALID' if refresh_ok else 'EXPIRED'} ({refresh_days:.1f} days remaining)")
            print(f"  Last saved:    {tokens.get('saved_at', 'unknown')}")
        return

    if not app_key or not app_secret:
        print("\n  Missing credentials! Set them in one of these ways:")
        print("  1. Create a .env file with SCHWAB_APP_KEY and SCHWAB_APP_SECRET")
        print("  2. Pass --app-key and --app-secret arguments")
        print("  3. Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables")
        print(f"\n  Example .env file ({ENV_FILE}):")
        print('  SCHWAB_APP_KEY="your-app-key-here"')
        print('  SCHWAB_APP_SECRET="your-app-secret-here"')
        sys.exit(1)

    # Refresh only
    if args.refresh:
        print("\n  Refreshing access token...")
        tokens = refresh_access_token(app_key, app_secret)
        if tokens:
            print("  Access token refreshed successfully!")
        else:
            print("  Refresh failed. Run full auth flow: python3 schwab_auth.py")
        return

    # Full auth flow
    tokens = run_auth_flow(app_key, app_secret, callback_url)
    if tokens:
        print("\n  Authentication complete! You're connected to Schwab.")
        print("  Run `python3 schwab_sync.py` to fetch and cache your account data.")
    else:
        print("\n  Authentication failed. Check your credentials and try again.")


if __name__ == "__main__":
    main()
