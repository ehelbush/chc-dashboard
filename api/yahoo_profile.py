"""Vercel serverless function to fetch Yahoo Finance fundamentals + news."""
from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import re


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _get_crumb_and_cookie():
    """Get a valid crumb and cookie for Yahoo Finance API."""
    try:
        req = urllib.request.Request("https://finance.yahoo.com/quote/AAPL/", headers=HEADERS)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        resp = opener.open(req, timeout=10)
        html = resp.read().decode("utf-8", errors="ignore")
        cookie_header = resp.headers.get("Set-Cookie", "")

        # Extract crumb from page content
        crumb_match = re.search(r'"crumb"\s*:\s*"([^"]+)"', html)
        crumb = crumb_match.group(1) if crumb_match else None

        # Get cookies from response
        cookies = []
        for header in resp.headers.get_all("Set-Cookie") or []:
            cookies.append(header.split(";")[0])
        cookie_str = "; ".join(cookies)

        return crumb, cookie_str, opener
    except Exception:
        return None, None, None


def fetch_json(url, cookie=None, opener=None):
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    if opener:
        resp = opener.open(req, timeout=10)
    else:
        resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        symbol = params.get("symbol", [None])[0]

        if not symbol:
            self._respond(400, {"error": "Missing symbol parameter"})
            return

        try:
            result = {}

            # 1. Quotesummary — profile, financials, key stats
            modules = "assetProfile,financialData,defaultKeyStatistics,incomeStatementHistory,earningsTrend"

            # Get crumb/cookie for authenticated requests
            crumb, cookie, opener = _get_crumb_and_cookie()

            # Try multiple API endpoints (Yahoo blocks unauthenticated v10 from server IPs)
            qs = None
            urls = []
            if crumb:
                urls.append(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={modules}&crumb={crumb}")
            urls.append(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={modules}")
            urls.append(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={modules}")

            try:
                for qs_url in urls:
                    try:
                        qs = fetch_json(qs_url, cookie=cookie, opener=opener)
                        if qs.get("quoteSummary", {}).get("result"):
                            break
                    except Exception:
                        continue
                if not qs:
                    raise Exception("All quoteSummary endpoints failed")
                qs_result = qs.get("quoteSummary", {}).get("result", [{}])[0]

                # Asset profile
                profile = qs_result.get("assetProfile", {})
                result["description"] = profile.get("longBusinessSummary", "")
                result["sector"] = profile.get("sector", "")
                result["industry"] = profile.get("industry", "")
                result["employees"] = profile.get("fullTimeEmployees")
                result["website"] = profile.get("website", "")

                # Financial data
                fd = qs_result.get("financialData", {})
                result["financials"] = {
                    "revenue": _raw(fd.get("totalRevenue")),
                    "revenue_growth": _raw(fd.get("revenueGrowth")),
                    "gross_margin": _raw(fd.get("grossMargins")),
                    "operating_margin": _raw(fd.get("operatingMargins")),
                    "ebitda_margin": _raw(fd.get("ebitdaMargins")),
                    "profit_margin": _raw(fd.get("profitMargins")),
                    "free_cash_flow": _raw(fd.get("freeCashflow")),
                    "operating_cash_flow": _raw(fd.get("operatingCashflow")),
                    "total_cash": _raw(fd.get("totalCash")),
                    "total_debt": _raw(fd.get("totalDebt")),
                    "current_ratio": _raw(fd.get("currentRatio")),
                    "return_on_equity": _raw(fd.get("returnOnEquity")),
                    "current_price": _raw(fd.get("currentPrice")),
                    "target_mean_price": _raw(fd.get("targetMeanPrice")),
                    "recommendation": fd.get("recommendationKey", ""),
                    "analyst_count": _raw(fd.get("numberOfAnalystOpinions")),
                }

                # Key stats
                ks = qs_result.get("defaultKeyStatistics", {})
                result["key_stats"] = {
                    "market_cap": _raw(ks.get("marketCap")),  # fallback
                    "enterprise_value": _raw(ks.get("enterpriseValue")),
                    "trailing_pe": _raw(ks.get("trailingPE") or ks.get("forwardPE")),
                    "forward_pe": _raw(ks.get("forwardPE")),
                    "peg_ratio": _raw(ks.get("pegRatio")),
                    "price_to_sales": _raw(ks.get("priceToSalesTrailing12Months")),
                    "price_to_book": _raw(ks.get("priceToBook")),
                    "ev_to_revenue": _raw(ks.get("enterpriseToRevenue")),
                    "ev_to_ebitda": _raw(ks.get("enterpriseToEbitda")),
                    "beta": _raw(ks.get("beta")),
                    "52wk_change": _raw(ks.get("52WeekChange")),
                    "short_pct_float": _raw(ks.get("shortPercentOfFloat")),
                    "shares_outstanding": _raw(ks.get("sharesOutstanding")),
                }

                # Revenue from income statement for TTM calculation
                inc = qs_result.get("incomeStatementHistory", {})
                stmts = inc.get("incomeStatementHistory", [])
                if stmts:
                    latest = stmts[0]
                    result["income"] = {
                        "total_revenue": _raw(latest.get("totalRevenue")),
                        "gross_profit": _raw(latest.get("grossProfit")),
                        "operating_income": _raw(latest.get("operatingIncome")),
                        "net_income": _raw(latest.get("netIncome")),
                        "ebitda": _raw(latest.get("ebitda")),
                    }
                    # Compute cash flow margin if we have OCF and revenue
                    rev = _raw(latest.get("totalRevenue"))
                    ocf = result["financials"].get("operating_cash_flow")
                    if rev and ocf and rev > 0:
                        result["financials"]["cash_flow_margin"] = round(ocf / rev, 4)

            except Exception as e:
                result["_qs_error"] = str(e)

            # 2. News via search API
            try:
                news_url = (
                    f"https://query1.finance.yahoo.com/v1/finance/search"
                    f"?q={symbol}&newsCount=5&quotesCount=0"
                )
                news_data = fetch_json(news_url, cookie=cookie, opener=opener)
                news_items = news_data.get("news", [])
                result["news"] = [
                    {
                        "title": n.get("title", ""),
                        "publisher": n.get("publisher", ""),
                        "link": n.get("link", ""),
                        "date": n.get("providerPublishTime"),
                    }
                    for n in news_items[:5]
                ]
            except Exception:
                result["news"] = []

            self._respond(200, result)

        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if code == 200:
            self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _raw(field):
    """Extract raw value from Yahoo's {raw: 123, fmt: '123'} format."""
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("raw")
    return field
