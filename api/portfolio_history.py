"""Vercel serverless function to serve portfolio history data."""
from http.server import BaseHTTPRequestHandler
import json
import os


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve the portfolio history from data/portfolio_history.json."""
        try:
            cache_paths = [
                os.path.join(os.path.dirname(__file__), "..", "data", "portfolio_history.json"),
                os.path.join("data", "portfolio_history.json"),
                "/var/task/data/portfolio_history.json",
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
                body = json.dumps(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=600")
                self.end_headers()
                self.wfile.write(body.encode())
            else:
                body = json.dumps([])
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
