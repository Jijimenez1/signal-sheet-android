"""Fetch a year of daily closes plus a current quote for every public Signal Sheet ticker.

Runs on GitHub Actions (see .github/workflows/prices.yml), which has normal internet access.
Reads the ticker list from docs/data/app.json (this week's picks + Strong buys) and writes
docs/data/history.json. The owner's private watchlist is never read or written here.

History sources, tried in order per ticker: Nasdaq API, StockAnalysis, Cboe, Yahoo Finance.
A source that answers "blocked" (HTTP 403/429) is skipped for the rest of the run.
Each result is checked before it is kept: at least 20 daily closes, the newest within
10 days, and no zero or negative prices. A ticker that fails keeps its previous data.

The quote ("Today" change) is always computed here from the previous regular-session close,
never taken from a source's own change field, so after-hours moves can't leak into "Today".
After the 4 PM close, the regular closing price is used and recorded as today's daily close.
"""
import csv, datetime as dt, io, json, pathlib, re, sys, threading, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "docs/data/app.json"
OUT = ROOT / "docs/data/history.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KEEP = 300  # trading days kept per ticker (about 14 months)
NY = ZoneInfo("America/New_York")
NQ = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def get(url, headers=None, timeout=12):
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


STALLS = {}  # source -> timeouts in a row
BLOCKED = set()  # sources that refused us this run (HTTP 403/429): skipped for the rest of the run


def guard(name):
    """Decorator: once a source blocks us, stop calling it for the rest of the run."""
    def wrap(fn):
        def inner(*a, **k):
            if name in BLOCKED:
                raise RuntimeError(f"{name}: skipped (blocked earlier this run)")
            try:
                r = fn(*a, **k)
                STALLS[name] = 0
                return r
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    BLOCKED.add(name)
                raise
            except (TimeoutError, urllib.error.URLError, ConnectionError):
                # a source that stalls instead of answering is as good as blocked: three in a row and we move on
                STALLS[name] = STALLS.get(name, 0) + 1
                if STALLS[name] >= 3:
                    BLOCKED.add(name)
                raise
        return inner
    return wrap


SA_KIND = {}  # ticker -> "s" (stock) or "e" (ETF) on StockAnalysis


SA_GAP = 0.0  # minimum seconds between StockAnalysis requests (set by bulk jobs so we don't hammer it)
_sa_lock, _sa_last = threading.Lock(), [0.0]


def sa_wait():
    if SA_GAP <= 0:
        return
    with _sa_lock:
        d = _sa_last[0] + SA_GAP - time.time()
        if d > 0:
            time.sleep(d)
        _sa_last[0] = time.time()


def sa_get(t, path):
    kinds = [SA_KIND[t]] if t in SA_KIND else (["e", "s"] if t in ("SPY", "QQQ", "VOO") else ["s", "e"])
    err = None
    for k in kinds:
        try:
            sa_wait()
            j = json.loads(get(f"https://stockanalysis.com/api/{path.format(k=k, t=t)}", {"Accept": "application/json"}))
            if j.get("data"):
                SA_KIND[t] = k
                return j["data"]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise
            err = e
    raise RuntimeError(f"stockanalysis: {err or 'no data'}")


@guard("stockanalysis")
def stockanalysis(t):
    """A year of daily candles from StockAnalysis (closes plus highs, lows and volume)."""
    rows = {}
    for p in sa_get(t, "charts/{k}/{t}/1Y/c"):
        if p.get("c") is None:
            continue
        d = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(p["t"]))).date().isoformat()
        rows[d] = round(float(p["c"]), 4)
        if p.get("h") is not None and p.get("l") is not None and p.get("v") is not None:
            HLV.setdefault(t, {})[d] = [round(float(p["h"]), 4), round(float(p["l"]), 4), int(p["v"])]
    if not rows:
        raise RuntimeError("stockanalysis: no rows")
    return sorted(rows.items())


@guard("cboe")
def cboe(t):
    j = json.loads(get(f"https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/{t}.json"))
    rows = {}
    for p in (j.get("data") or [])[-320:]:
        if p.get("close"):
            rows[p["date"]] = round(float(p["close"]), 4)
            try:
                HLV.setdefault(t, {})[p["date"]] = [round(float(p["high"]), 4), round(float(p["low"]), 4), int(float(p["volume"]))]
            except (KeyError, TypeError, ValueError):
                pass
    if not rows:
        raise RuntimeError("cboe: no rows")
    return sorted(rows.items())


@guard("nasdaq")
def nasdaq(t):
    start = (dt.date.today() - dt.timedelta(days=430)).isoformat()
    for cls in ("stocks", "etf"):
        j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass={cls}&fromdate={start}&limit=9999", NQ))
        rows = {}
        for r in ((j.get("data") or {}).get("tradesTable") or {}).get("rows") or []:
            m, d, y = r["date"].split("/")
            rows[f"{y}-{m}-{d}"] = round(num(r["close"]), 4)
            try:  # highs, lows and volume feed the volume and risk signals
                HLV.setdefault(t, {})[f"{y}-{m}-{d}"] = [round(num(r["high"]), 4), round(num(r["low"]), 4), int(num(r["volume"]))]
            except (ValueError, KeyError):
                pass
        if rows:
            return sorted(rows.items())
    raise RuntimeError("nasdaq: no rows")


HLV = {}  # ticker -> {date: [high, low, volume]} from the Nasdaq history
HLV_KEEP = 130


def hlv_rows(t, rows):
    m = HLV.get(t) or {}
    return [[d] + m[d] for d, _ in rows[-HLV_KEEP:] if d in m]


# Nasdaq first; it sometimes blocks GitHub's servers for hours, so StockAnalysis and Cboe back it up.
SOURCES = [("Nasdaq", nasdaq), ("StockAnalysis", stockanalysis), ("Cboe", cboe), ("Yahoo Finance", guard("yahoo")(yahoo))]


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


def sa_quote(t):
    """Regular-session price from StockAnalysis: (price, status, stamp) or None."""
    try:
        if "stockanalysis" in BLOCKED:
            return None
        d = sa_get(t, "quotes/{k}/{t}")
        p = d.get("p")
        if not p or p <= 0:
            return None
        return float(p), ("Open" if d.get("ms") == "open" else "Closed"), (d.get("u") or "").replace(" EST", " ET").replace(" EDT", " ET").replace(", 20", ", 20")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            BLOCKED.add("stockanalysis")
        return None
    except Exception:
        return None


def live_quote(t):
    """Nasdaq first, StockAnalysis when Nasdaq has nothing. Returns ((price, status, stamp), source) or (None, None)."""
    q = nasdaq_regular(t) if "nasdaq" not in BLOCKED else None
    if q:
        return q, "Nasdaq"
    q = sa_quote(t)
    return (q, "StockAnalysis") if q else (None, None)


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
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                BLOCKED.add("nasdaq")
                return None
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


def make_quote(rows, live, now=None, source="Nasdaq"):
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
        price, src = live[0], source
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


LONG = ROOT / "docs/data/long.json"
LONG_DAYS = 3  # refresh each ticker's all-time series this often


def update_long(tickers, last_close, report):
    """All-time history for the public tickers (docs/data/long.json); only stale or missing ones are fetched."""
    try:
        import extras
        cur = json.loads(LONG.read_text()).get("tickers", {}) if LONG.exists() else {}
        now = dt.datetime.now(dt.timezone.utc)
        out, changed = {}, False
        for t in sorted(tickers):
            old = cur.get(t)
            age = (now - dt.datetime.fromisoformat(old["fetched"].replace("Z", "+00:00"))).days if old and old.get("fetched") else 99
            if old and age < LONG_DAYS:
                out[t] = old
                continue
            rows = extras.long_history(t, last_close.get(t), etf=(t == "SPY"))
            if rows:
                out[t] = {"t": t, "source": "StockAnalysis", "rows": rows, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
                changed = True
                report.append(f"{t}: all-time history, {len(rows)} points since {rows[0][0]}")
            elif old:
                out[t] = old
            else:
                report.append(f"{t}: no all-time history")
            time.sleep(0.4)
        if changed or set(out) != set(cur):
            LONG.write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": out}, separators=(",", ":")))
            report.append(f"wrote long.json: {len(out)} tickers, {LONG.stat().st_size} bytes")
    except Exception as e:  # never let the extras break the price feed
        report.append(f"all-time history skipped: {str(e)[:120]}")


def short_data(report):
    try:
        import extras
        finra = extras.finra_short()
        try:
            shares = extras.shares_outstanding()
        except Exception:
            shares = {}
        report.append(f"short interest: {len(finra)} symbols, shares outstanding for {len(shares)}")
        return lambda t: extras.short_for(t, finra, shares)
    except Exception as e:
        report.append(f"short interest skipped: {str(e)[:120]}")
        return lambda t: None


def main(quick=False):
    """quick=True refreshes only the live quotes (used between full runs during market hours)."""
    old = json.loads(OUT.read_text()).get("tickers", {}) if OUT.exists() else {}
    out, report = {}, []
    now = dt.datetime.now(dt.timezone.utc)
    short_of = (lambda t: None) if quick else short_data(report)
    for t in sorted(tickers_from_app()):
        prev = old.get(t) or {}
        fresh = quick and prev.get("rows") and (dt.date.today() - dt.date.fromisoformat(prev["rows"][-1][0])).days <= 5
        if fresh:  # quotes-only pass: reuse the stored daily history
            name, rows = prev.get("source", ""), [(d, c) for d, c in prev["rows"]]
            # drop a close we appended ourselves for a session that is still running
            if rows and rows[-1][0] == session(now)[0] and session(now)[1]:
                rows = rows[:-1]
        else:
            name, rows = history(t, report)
        if not rows:
            if prev:
                out[t] = prev
                report.append(f"{t}: kept previous data")
            continue
        live, qsrc = live_quote(t)
        quote, rows = make_quote(rows[-KEEP:], live, source=qsrc or "Nasdaq")
        out[t] = {"t": t, "source": name, "rows": [[d, c] for d, c in rows[-KEEP:]], "quote": quote, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        hl = prev.get("hlv") if fresh else hlv_rows(t, rows)
        if hl:
            out[t]["hlv"] = hl
        sh = short_of(t) or prev.get("short")
        if sh:
            out[t]["short"] = sh
        report.append(f"{t}: {name}, {len(rows)} days through {rows[-1][0]}, {quote['price']:.2f} {quote['changePct']:+.2f}% ({quote['asOf']})")
        time.sleep(0.3)
    print("\n".join(r for r in report if not quick or "failed" in r or "kept" in r))
    if BLOCKED:
        print("blocked this run:", ", ".join(sorted(BLOCKED)))
    if not out:
        print("No prices fetched from any source; leaving history.json unchanged.")
        return
    OUT.write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": out}, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} tickers, {OUT.stat().st_size} bytes")
    if quick:
        return
    report = []
    update_long(out.keys(), {t: x["rows"][-1][1] for t, x in out.items() if x.get("rows")}, report)
    print("\n".join(report))


if __name__ == "__main__":
    main(quick="--quotes" in sys.argv)
