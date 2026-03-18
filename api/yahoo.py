"""Vercel serverless function to fetch Yahoo Finance data (no CORS issues)."""
from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import time


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse query params
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        symbol = params.get("symbol", [None])[0]
        years = int(params.get("years", [6])[0])

        if not symbol:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing symbol parameter"}).encode())
            return

        try:
            end = int(time.time())
            start = end - years * 365 * 86400 - 30 * 86400
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                f"?period1={start}&period2={end}&interval=1d"
            )

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read().decode())

            result = raw["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            adj = result["indicators"].get("adjclose", [{}])
            adjclose = adj[0].get("adjclose") if adj else None

            dates = []
            closes = []
            volumes = []
            for i in range(len(ts)):
                c = (adjclose[i] if adjclose and adjclose[i] is not None else q["close"][i])
                v = q["volume"][i]
                if c is not None and v is not None:
                    dates.append(time.strftime("%Y-%m-%d", time.gmtime(ts[i])))
                    closes.append(round(c, 4))
                    volumes.append(int(v))

            name = result.get("meta", {}).get("shortName") or result.get("meta", {}).get("symbol") or symbol

            body = json.dumps({
                "symbol": symbol.upper(),
                "name": name,
                "dates": dates,
                "closes": closes,
                "volumes": volumes,
            })

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
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
