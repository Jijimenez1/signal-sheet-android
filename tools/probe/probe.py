import json, sys, pathlib, datetime as dt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fetch_prices import get, NQ
def show(name, fn):
    try: print("==", name, "->", fn())
    except Exception as e: print("==", name, "FAILED", repr(e)[:300])
def finra():
    d = dt.date.today(); out = []
    for i in range(60):
        x = d - dt.timedelta(days=i)
        try:
            txt = get(f"https://cdn.finra.org/equity/otcmarket/biweekly/shrt{x:%Y%m%d}.csv", timeout=60)
            lines = txt.splitlines()
            pick = [l for l in lines if l.split("|")[1:2] in (["AAPL"], ["GME"], ["SPY"], ["MU"])]
            out.append((x.isoformat(), len(lines), lines[0], pick)); 
            if len(out) >= 2: break
        except Exception as e:
            if i < 3: out.append((x.isoformat(), repr(e)[:80]))
    return out
show("finra", finra)
def sa(path):
    j = json.loads(get("https://stockanalysis.com/api/charts/" + path, timeout=30)); d = j["data"]
    return len(d), d[0], d[-3:]
show("sa AAPL max", lambda: sa("s/AAPL/MAX/l")); show("sa SPY max", lambda: sa("e/SPY/MAX/l")); show("sa KO max", lambda: sa("s/KO/MAX/l"))
show("sa BRK.B max", lambda: sa("s/BRK.B/MAX/l")); show("sa ETON", lambda: sa("s/ETON/MAX/l")); show("sa AAPL 5Y", lambda: sa("s/AAPL/5Y/l"))
def scr():
    j = json.loads(get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", NQ, timeout=60)); r = j["data"]["rows"]
    return len(r), [x for x in r if x["symbol"] in ("AAPL", "GME")]
show("screener", scr)
