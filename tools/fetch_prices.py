"""Fetch a year of daily closes plus a current quote for every public Signal Sheet ticker.

Runs on GitHub Actions (see .github/workflows/prices.yml), which has normal internet access.
Reads the ticker list from docs/data/app.json (this week's picks + Strong buys) and writes
docs/data/history.json. The owner's private watchlist is never read or written here.

History sources, tried in order per ticker: Nasdaq API, Yahoo Finance chart API, Stooq CSV.
Each result is checked before it is kept: at least 20 daily closes, the newest within
10 days, and no zero or negative prices. A ticker that fails keeps its previous data.

The quote ("Today" change) is always computed here from the previous regular-session close,
never taken from a source's own change field, so after-hours moves can't leak into "Today".
After the 4 PM close, the regular closing price is used and recorded as today's daily close.
"""
import csv, datetime as dt, io, json, pathlib, re, sys, time, urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "docs/data/app.json"
OUT = ROOT / "docs/data/history.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KEEP = 300  # trading days kept per ticker (about 14 months)
NY = ZoneInfo("America/New_York")
NQ = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def num(x):
    return float(str(x).replace("$", "").replace(",", "").replace("%", "").replace("+", "").strip())


# ---------- daily history ----------
def yahoo(t):
    sym = t.replace(".", "-")
    last_err = None
    for host in ("query1", "query2"):
        try:
            j = json.loads(get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d&includePrePost=false"))
            res = j["chart"]["result"][0]
            ts, closes = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
            off = int(res["meta"].get("gmtoffset") or 0)
            rows = {}
            for s, c in zip(ts, closes):
                if c is not None:
                    rows[dt.datetime.fromtimestamp(s + off, dt.timezone.utc).strftime("%Y-%m-%d")] = round(float(c), 4)
            return sorted(rows.items())
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"yahoo: {last_err}")


def stooq(t):
    txt = get(f"https://stooq.com/q/d/l/?s={t.lower().replace('.', '-')}.us&i=d")
    rows = {r["Date"]: round(float(r["Close"]), 4) for r in csv.DictReader(io.StringIO(txt)) if r.get("Close") not in (None, "", "N/D")}
    if not rows:
        raise RuntimeError("stooq: no rows")
    return sorted(rows.items())


def nasdaq(t):
    start = (dt.date.today() - dt.timedelta(days=430)).isoformat()
    for cls in ("stocks", "etf"):
        j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass={cls}&fromdate={start}&limit=9999", NQ))
        rows = {}
        for r in ((j.get("data") or {}).get("tradesTable") or {}).get("rows") or []:
            m, d, y = r["date"].split("/")
            rows[f"{y}-{m}-{d}"] = round(num(r["close"]), 4)
        if rows:
            return sorted(rows.items())
    raise RuntimeError("nasdaq: no rows")


SOURCES = [("Nasdaq", nasdaq), ("Yahoo Finance", yahoo), ("Stooq", stooq)]  # Nasdaq first: the others block GitHub runners


def valid(rows):
    if len(rows) < 20:
        return "fewer than 20 rows"
    if any(c <= 0 for _, c in rows):
        return "non-positive price"
    if (dt.date.today() - dt.date.fromisoformat(rows[-1][0])).days > 10:
        return f"stale (newest {rows[-1][0]})"
    return None


def history(t, report):
    for name, fn in SOURCES:
        try:
            rows = fn(t)
            why = valid(rows)
            if why:
                report.append(f"{t}: {name} rejected ({why})")
                continue
            return name, rows
        except Exception as e:
            report.append(f"{t}: {name} failed ({str(e)[:80]})")
    return None, None


# ---------- current quote ----------
def session(now=None):
    """(date of the latest regular session that has started, is the market open right now)."""
    n = (now or dt.datetime.now(dt.timezone.utc)).astimezone(NY)
    d, mins = n.date(), n.hour * 60 + n.minute
    if n.weekday() < 5 and mins >= 9 * 60 + 30:
        return d.isoformat(), mins < 16 * 60
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat(), False


def nasdaq_regular(t):
    """Latest regular-session price from Nasdaq: live during the session, the official close after it.
    Returns (price, status, stamp) or None."""
    for cls in ("stocks", "etf"):
        try:
            j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/info?assetclass={cls}", NQ))
            d = j.get("data") or {}
            status = (d.get("marketStatus") or "").strip()
            pri, sec = d.get("primaryData") or {}, d.get("secondaryData") or {}
            # Outside the session Nasdaq puts the extended-hours trade in primaryData and the
            # regular close in secondaryData; prefer the regular close whenever it is there.
            if status.lower() == "open":
                src = pri
            elif sec.get("lastSalePrice"):
                src = sec
            else:
                return None  # closed with no regular-close field: never risk an extended-hours price
            if src.get("lastSalePrice"):
                stamp = (src.get("lastTradeTimestamp") or "").replace("DATA AS OF", "").replace("Closed at", "").strip()
                return num(src["lastSalePrice"]), status, stamp
        except Exception:
            pass
    return None


def stamp_date(stamp):
    """'Nov 4, 2026 4:00 PM ET' -> '2026-11-04', or None."""
    m = re.search(r"([A-Z][a-z]{2})\w* (\d{1,2}), (\d{4})", stamp or "")
    if not m:
        return None
    try:
        return dt.datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%b %d %Y").date().isoformat()
    except ValueError:
        return None


def make_quote(rows, live, now=None):
    """rows: [(date, close)] oldest first. Returns (quote, rows) with today's close appended after the bell."""
    sdate, is_open = session(now)
    sd = stamp_date(live[2]) if live else None
    if sd and sd <= sdate:  # trust the quote's own date (handles market holidays)
        if sd < sdate:
            is_open = False
        sdate = sd
    rows = list(rows)
    price, stamp, src = rows[-1][1], dt.date.fromisoformat(rows[-1][0]).strftime("%b %-d") + " close", None
    if live and live[0] > 0 and abs(live[0] / rows[-1][1] - 1) < 0.35:  # sanity check against the last close
        price, src = live[0], "Nasdaq"
        if is_open:
            stamp = (live[2] or "").strip() or "live"
        else:
            stamp = dt.date.fromisoformat(sdate).strftime("%b %-d") + " close"
            if rows[-1][0] < sdate and not is_open:
                rows.append((sdate, round(price, 4)))  # record today's close until the official history catches up
    # previous regular close = last close before the session the price belongs to
    pdate = sdate if (src or rows[-1][0] == sdate) else rows[-1][0]
    before = [c for d, c in rows if d < pdate]
    prev = before[-1] if before else rows[0][1]
    yr = [c for _, c in rows[-252:]] + [price]
    quote = {"price": round(price, 4), "changePct": round((price / prev - 1) * 100, 4), "asOf": stamp,
             "source": src or "daily close", "high52": round(max(yr), 4), "low52": round(min(yr), 4)}
    return quote, rows


def tickers_from_app():
    app = json.loads(APP.read_text())
    ts = set()
    for w in app.get("weeks", [])[:1]:
        ts |= {p["t"] for p in w.get("picks", []) if p.get("t")}
    ts |= {p["t"] for p in (app.get("signals") or {}).get("picks", []) if p.get("t")}
    ts.add("SPY")  # market benchmark
    return ts


def main():
    old = json.loads(OUT.read_text()).get("tickers", {}) if OUT.exists() else {}
    out, report = {}, []
    now = dt.datetime.now(dt.timezone.utc)
    for t in sorted(tickers_from_app()):
        name, rows = history(t, report)
        if not rows:
            if t in old:
                out[t] = old[t]
                report.append(f"{t}: kept previous data")
            continue
        live = nasdaq_regular(t)
        quote, rows = make_quote(rows[-KEEP:], live)
        report.append(f"{t}: nasdaq quote {live}")
        out[t] = {"t": t, "source": name, "rows": [[d, c] for d, c in rows[-KEEP:]], "quote": quote, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        report.append(f"{t}: {name}, {len(rows)} days through {rows[-1][0]}, {quote['price']:.2f} {quote['changePct']:+.2f}% ({quote['asOf']})")
        time.sleep(0.3)
    print("\n".join(report))
    if not out:
        sys.exit("No prices fetched from any source; leaving history.json unchanged.")
    OUT.write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": out}, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} tickers, {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
