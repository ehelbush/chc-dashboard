"""Vercel serverless function to save ticker_params.json to GitHub via the GitHub API."""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import base64


GITHUB_REPO = "ehelbush/chc-dashboard"
FILE_PATH = "data/ticker_params.json"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        token = os.environ.get("GH_PAT")
        if not token:
            self._respond(500, {"error": "GH_PAT not configured"})
            return

        # Read request body
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._respond(400, {"error": "Empty request body"})
            return

        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._respond(400, {"error": "Invalid JSON"})
            return

        params = body.get("params")
        ticker = body.get("ticker")
        message = body.get("message", "Update ticker params")

        if not params:
            self._respond(400, {"error": "Missing 'params' field"})
            return

        try:
            # Get current file to obtain its SHA (required for update)
            current = self._github_get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}",
                token,
            )
            sha = current["sha"]
            current_content = json.loads(
                base64.b64decode(current["content"]).decode("utf-8")
            )

            # Merge: if single ticker update, patch into existing; otherwise full replace
            if ticker and isinstance(params, dict):
                current_content[ticker] = params
                updated = current_content
                message = f"Update params for {ticker}"
            else:
                updated = params
                message = message or "Update all ticker params"

            # Sort keys for clean diffs
            new_content = json.dumps(updated, indent=2, sort_keys=True) + "\n"
            encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

            # Commit the file
            self._github_put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}",
                token,
                {
                    "message": message,
                    "content": encoded,
                    "sha": sha,
                },
            )

            self._respond(200, {"ok": True, "message": message})

        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _github_get(self, url, token):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "chc-dashboard",
        })
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def _github_put(self, url, token, data):
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            method="PUT",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "chc-dashboard",
            },
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
