import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fetch_prices import get, NQ
def show(name, fn):
    try: print("==", name, "->", fn())
    except Exception as e: print("==", name, "FAILED", repr(e)[:300])
def nq_hist(t, start):
    j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass=stocks&fromdate={start}&limit=99999", NQ, timeout=60))
    rows = j["data"]["tradesTable"]["rows"]; return len(rows), rows[-1], rows[0], j["data"].get("totalRecords")
def nq_chart(t, start):
    j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/chart?assetclass=stocks&fromdate={start}&todate=2026-11-09", NQ, timeout=60))
    c = j["data"]["chart"]; return len(c), c[0], c[-1]
def nq_short(t):
    j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/short-interest?assetClass=stocks", NQ, timeout=30))
    return json.dumps(j)[:900]
def yahoo(t, host):
    return get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{t}?range=max&interval=1mo", timeout=30)[:300]
def stooq(t):
    return get(f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=m", timeout=30)[:300]
def url(u, h=None):
    return get(u, h, timeout=30)[:400]
for t in ("AAPL", "KO", "MU"):
    show(f"nasdaq hist {t} 1970", lambda: nq_hist(t, "1970-01-01"))
show("nasdaq chart AAPL 1980", lambda: nq_chart("AAPL", "1980-01-01"))
show("nasdaq chart KO 1960", lambda: nq_chart("KO", "1960-01-01"))
for t in ("AAPL", "GME", "SPY"): show(f"short {t}", lambda: nq_short(t))
show("yahoo q1", lambda: yahoo("AAPL", "query1")); show("yahoo q2", lambda: yahoo("AAPL", "query2"))
show("stooq", lambda: stooq("AAPL"))
show("stockanalysis hist", lambda: url("https://stockanalysis.com/api/symbol/s/AAPL/history?type=full"))
show("stockanalysis chart", lambda: url("https://stockanalysis.com/api/charts/s/AAPL/MAX/l"))
show("macrotrends", lambda: url("https://www.macrotrends.net/assets/php/stock_price_history.php?t=AAPL"))
show("tiingo-free", lambda: url("https://api.tiingo.com/tiingo/daily/aapl/prices?startDate=1980-01-01"))
show("finviz short", lambda: url("https://finviz.com/quote.ashx?t=GME"))
