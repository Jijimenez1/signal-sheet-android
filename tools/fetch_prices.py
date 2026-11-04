"""Fetch a year of daily closes plus a current quote for every public Signal Sheet ticker.

Runs on GitHub Actions (see .github/workflows/prices.yml), which has normal internet access.
Reads the ticker list from docs/data/app.json (this week's picks + Strong buys) and writes
docs/data/history.json. The owner's private watchlist is never read or written here.

Sources, tried in order per ticker: Yahoo Finance chart API, Stooq CSV, Nasdaq API.
Each result is checked before it is kept: at least 20 daily closes, the newest within
10 days, and no zero or negative prices. A ticker that fails keeps its previous data.
"""
import csv, datetime as dt, io, json, pathlib, sys, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "docs/data/app.json"
OUT = ROOT / "docs/data/history.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KEEP = 300  # trading days kept per ticker (about 14 months)


def get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo(t):
    sym = t.replace(".", "-")
    last_err = None
    for host in ("query1", "query2"):
        try:
            j = json.loads(get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d&includePrePost=false"))
            res = j["chart"]["result"][0]
            meta, ts = res["meta"], res.get("timestamp") or []
            closes = res["indicators"]["quote"][0]["close"]
            off = int(meta.get("gmtoffset") or 0)
            rows = {}
            for s, c in zip(ts, closes):
                if c is None:
                    continue
                d = dt.datetime.fromtimestamp(s + off, dt.timezone.utc).strftime("%Y-%m-%d")
                rows[d] = round(float(c), 4)
            price = meta.get("regularMarketPrice")
            when = meta.get("regularMarketTime")
            extra = {k: meta.get(k) for k in ("fiftyTwoWeekHigh", "fiftyTwoWeekLow") if meta.get(k) is not None}
            return sorted(rows.items()), price, when, extra
        except Exception as e:  # try the other host, then the next source
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"yahoo: {last_err}")


def stooq(t):
    txt = get(f"https://stooq.com/q/d/l/?s={t.lower().replace('.', '-')}.us&i=d")
    rd = csv.DictReader(io.StringIO(txt))
    rows = {r["Date"]: round(float(r["Close"]), 4) for r in rd if r.get("Close") not in (None, "", "N/D")}
    if not rows:
        raise RuntimeError("stooq: no rows")
    return sorted(rows.items()), None, None, {}


NQ = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
num = lambda x: float(str(x).replace("$", "").replace(",", "").replace("%", "").replace("+", "").strip())


def nasdaq(t):
    start = (dt.date.today() - dt.timedelta(days=430)).isoformat()
    for cls in ("stocks", "etf"):
        j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass={cls}&fromdate={start}&limit=9999", NQ))
        rows = {}
        for r in ((j.get("data") or {}).get("tradesTable") or {}).get("rows") or []:
            m, d, y = r["date"].split("/")
            rows[f"{y}-{m}-{d}"] = round(num(r["close"]), 4)
        if rows:
            return sorted(rows.items()), None, None, {}
    raise RuntimeError("nasdaq: no rows")


def nasdaq_live(t):
    """Latest trade (intraday during market hours) from Nasdaq's quote endpoint."""
    for cls in ("stocks", "etf"):
        try:
            j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/info?assetclass={cls}", NQ))
            pd = (j.get("data") or {}).get("primaryData") or {}
            if pd.get("lastSalePrice"):
                return num(pd["lastSalePrice"]), num(pd.get("percentageChange") or 0), (pd.get("lastTradeTimestamp") or "").replace("DATA AS OF ", "").strip()
        except Exception:
            pass
    return None


SOURCES = [("Yahoo Finance", yahoo), ("Stooq", stooq), ("Nasdaq", nasdaq)]


def valid(rows):
    if len(rows) < 20:
        return "fewer than 20 rows"
    if any(c <= 0 for _, c in rows):
        return "non-positive price"
    newest = dt.date.fromisoformat(rows[-1][0])
    if (dt.date.today() - newest).days > 10:
        return f"stale (newest {newest})"
    return None


def main():
    app = json.loads(APP.read_text())
    tickers = set()
    for w in app.get("weeks", [])[:1]:
        tickers |= {p["t"] for p in w.get("picks", []) if p.get("t")}
    tickers |= {p["t"] for p in (app.get("signals") or {}).get("picks", []) if p.get("t")}
    tickers.add("SPY")  # market benchmark
    old = json.loads(OUT.read_text()).get("tickers", {}) if OUT.exists() else {}
    out, report = {}, []
    now = dt.datetime.now(dt.timezone.utc)
    for t in sorted(tickers):
        got = None
        for name, fn in SOURCES:
            try:
                rows, price, when, extra = fn(t)
                why = valid(rows)
                if why:
                    report.append(f"{t}: {name} rejected ({why})")
                    continue
                got = (name, rows, price, when, extra)
                break
            except Exception as e:
                report.append(f"{t}: {name} failed ({str(e)[:80]})")
        if not got:
            if t in old:
                out[t] = old[t]
                report.append(f"{t}: kept previous data")
            continue
        name, rows, price, when, extra = got
        rows = rows[-KEEP:]
        live = nasdaq_live(t) if not price else None
        last = rows[-1][1]
        prev = rows[-2][1] if len(rows) > 1 else last
        px = float(price) if price else last
        asof = dt.datetime.fromtimestamp(when, dt.timezone.utc) if when else None
        quote = {
            "price": round(px, 4),
            "changePct": round((px / prev - 1) * 100, 4),  # vs the previous trading day's close
            "asOf": (asof.strftime("%b %-d, %H:%M UTC") if asof else dt.date.fromisoformat(rows[-1][0]).strftime("%b %-d") + " close"),
            "source": name,
        }
        if live and live[0] > 0 and abs(live[0] / last - 1) < 0.35:  # sanity check against the last close
            quote.update(price=round(live[0], 4), changePct=round(live[1], 4), asOf=live[2] or quote["asOf"], source="Nasdaq")
        yr = [c for _, c in rows[-252:]] + [quote["price"]]
        quote["high52"] = extra.get("fiftyTwoWeekHigh") or round(max(yr), 4)
        quote["low52"] = extra.get("fiftyTwoWeekLow") or round(min(yr), 4)
        out[t] = {"t": t, "source": name, "rows": [[d, c] for d, c in rows], "quote": quote, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        report.append(f"{t}: {name}, {len(rows)} days through {rows[-1][0]}, quote {quote['price']:.2f} ({quote['asOf']})")
        time.sleep(0.4)
    if not out:
        print("\n".join(report)); sys.exit("No prices fetched from any source; leaving history.json unchanged.")
    OUT.write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": out}, separators=(",", ":")))
    print("\n".join(report))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} tickers, {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
