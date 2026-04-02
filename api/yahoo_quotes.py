"""Vercel serverless function to fetch live Yahoo Finance quotes for multiple symbols."""
from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse


HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        symbols_str = params.get("symbols", [None])[0]

        if not symbols_str:
            self._respond(400, {"error": "Missing symbols parameter"})
            return

        symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
        if not symbols:
            self._respond(400, {"error": "No valid symbols provided"})
            return

        try:
            joined = ",".join(symbols)
            url = (
                f"https://query1.finance.yahoo.com/v7/finance/quote"
                f"?symbols={urllib.parse.quote(joined)}"
                f"&fields=symbol,regularMarketPrice,regularMarketChange,"
                f"regularMarketChangePercent,regularMarketPreviousClose,"
                f"regularMarketTime,marketState"
            )
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())

            quotes = {}
            for q in raw.get("quoteResponse", {}).get("result", []):
                sym = q.get("symbol", "")
                quotes[sym] = {
                    "price": q.get("regularMarketPrice"),
                    "change": q.get("regularMarketChange"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "prev_close": q.get("regularMarketPreviousClose"),
                    "market_state": q.get("marketState", ""),
                    "time": q.get("regularMarketTime"),
                }

            self._respond(200, {"quotes": quotes, "count": len(quotes)})

        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if code == 200:
            self.send_header("Cache-Control", "s-maxage=30, stale-while-revalidate=60")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
