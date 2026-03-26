"""Vercel serverless function to serve cached Schwab account data."""
from http.server import BaseHTTPRequestHandler
import json
import os


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve the cached Schwab data from data/schwab_cache.json."""
        try:
            # In Vercel, the working directory is the project root
            cache_paths = [
                os.path.join(os.path.dirname(__file__), "..", "data", "schwab_cache.json"),
                os.path.join("data", "schwab_cache.json"),
                "/var/task/data/schwab_cache.json",
            ]

            data = None
            for path in cache_paths:
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    continue

            if data:
                # Scrub sensitive data before serving
                # Remove account numbers, just keep masked versions
                for acct in data.get("accounts", []):
                    acct.pop("account_hash", None)

                body = json.dumps(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=600")
                self.end_headers()
                self.wfile.write(body.encode())
            else:
                # No cache file — return empty state
                body = json.dumps({
                    "status": "not_configured",
                    "synced_at": None,
                    "accounts": [],
                    "benchmarks": {},
                    "portfolio_summary": {},
                    "auth_status": {
                        "connected": False,
                        "needs_reauth": True,
                        "last_sync": None,
                    },
                    "message": "Schwab integration not configured. Run schwab_auth.py and schwab_sync.py locally.",
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body.encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
