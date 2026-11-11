import json, urllib.request, gzip, time
def get(url, h=None, timeout=30):
    req = urllib.request.Request(url, headers=h or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
        return b.decode("utf-8", "replace")
def show(name, fn):
    try: print("==", name, "->", str(fn())[:600])
    except Exception as e: print("==", name, "FAILED", repr(e)[:200])
UA1 = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
UA2 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
full = {"User-Agent": UA2, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/", "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"'}
NQU = "https://api.nasdaq.com/api/quote/AAPL/info?assetclass=stocks"
show("nasdaq old headers", lambda: get(NQU, {"User-Agent": UA1, "Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}))
show("nasdaq full headers", lambda: get(NQU, full))
show("nasdaq curl-like", lambda: get(NQU, {"User-Agent": "curl/8.5.0", "Accept": "*/*"}))
show("nasdaq hist full", lambda: get("https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2026-10-01&limit=50", full))
show("nasdaq screener full", lambda: get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", full, 60)[:300])
SA = {"User-Agent": UA2, "Accept": "application/json"}
def sa(path):
    j = json.loads(get("https://stockanalysis.com/api/" + path, SA)); d = j.get("data", j)
    return (len(d), d[:1], d[-2:]) if isinstance(d, list) else json.dumps(d)[:500]
for p in ("charts/s/AAPL/1Y/l", "charts/s/AAPL/1Y/c", "charts/s/AAPL/1D/l", "charts/s/AAPL/5D/l", "charts/e/SPY/1Y/c", "quotes/s/AAPL", "quotes/e/SPY", "symbol/s/AAPL/history?type=full&range=1Y", "screener/s/f?m=marketCap&s=desc&c=no,s,n,marketCap,price,change,volume,sharesOut,shortFloat,shortRatio&cn=5&p=1&i=stocks", "screener/s/bd/marketCap+price+change+sharesOut+shortFloat+shortRatio.json"):
    show("sa " + p, lambda: sa(p)); time.sleep(0.5)
show("finra", lambda: get("https://cdn.finra.org/equity/otcmarket/biweekly/shrt20261015.csv", {"User-Agent": UA2}, 60)[:150])
show("stooq", lambda: get("https://stooq.com/q/d/l/?s=aapl.us&i=d", {"User-Agent": UA2})[:200])
show("yahoo", lambda: get("https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d", {"User-Agent": UA2})[:200])
show("cboe", lambda: get("https://cdn.cboe.com/api/global/delayed_quotes/quotes/AAPL.json", {"User-Agent": UA2})[:400])
show("cboe hist", lambda: get("https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/AAPL.json", {"User-Agent": UA2})[:300])
