"""Extra market data shared by the price feeds: all-time history, short interest, shares outstanding.

All-time history: StockAnalysis chart API (daily closes since listing, split-adjusted), thinned to
monthly points for older years and weekly points for the last two years so files stay small.
Short interest: FINRA's twice-monthly Equity Short Interest file (every US-listed stock in one file).
Shares outstanding: Nasdaq screener market cap / last sale, used for "short % of shares".
Nothing here is estimated: a field that can't be fetched is left out.
"""
import datetime as dt, json, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NQ = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def num(x):
    return float(str(x).replace("$", "").replace(",", "").replace("%", "").replace("+", "").replace('"', "").strip())


# ---------- all-time history ----------
def sa_all(t, etf=False):
    """Daily closes since listing: [(YYYY-MM-DD, close)] oldest first, or None."""
    for kind in (("e", "s") if etf else ("s", "e")):
        try:
            j = json.loads(get(f"https://stockanalysis.com/api/charts/{kind}/{t}/MAX/l"))
            rows = {}
            for p in j.get("data") or []:
                if p.get("c") is not None and p["c"] > 0:
                    rows[(dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(p["t"]))).date().isoformat()] = float(p["c"])
            if len(rows) >= 20:
                return sorted(rows.items())
        except Exception:
            pass
    return None


def thin(rows, today=None, weekly_years=2):
    """Keep the last close of each month, and of each week for the most recent years."""
    today = today or dt.date.today()
    cut = (today - dt.timedelta(days=int(365.25 * weekly_years))).isoformat()
    out = {}
    for d, c in rows:
        if d >= cut:
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            key = f"w{y}-{w:02d}"
        else:
            key = "m" + d[:7]
        out[key] = (d, c)
    sig = lambda c: round(c, 4) if c < 10 else round(c, 2)
    return [[d, sig(c)] for d, c in sorted(out.values())]


def long_history(t, daily_last=None, etf=False):
    """Thinned all-time series, checked against the latest daily close so a wrong symbol can't slip in."""
    rows = sa_all(t, etf)
    if not rows:
        return None
    if (dt.date.today() - dt.date.fromisoformat(rows[-1][0])).days > 10:
        return None
    if daily_last and abs(rows[-1][1] / daily_last - 1) > 0.25:
        return None
    return thin(rows)


# ---------- short interest ----------
def finra_short(today=None):
    """Latest FINRA short-interest file -> {SYMBOL: {date, shares, prev, avgVol, dtc, changePct}}."""
    today = today or dt.date.today()
    for i in range(50):
        x = today - dt.timedelta(days=i)
        try:
            txt = get(f"https://cdn.finra.org/equity/otcmarket/biweekly/shrt{x:%Y%m%d}.csv", timeout=90)
        except Exception:
            continue
        lines = txt.splitlines()
        if len(lines) < 1000:
            continue
        head = [h.strip('"') for h in lines[0].split("|")]
        ix = {h: k for k, h in enumerate(head)}
        out = {}
        for ln in lines[1:]:
            f = [v.strip('"') for v in ln.split("|")]
            try:
                sym = f[ix["symbolCode"]].strip().upper().replace("/", ".").replace(" ", ".")
                cur = num(f[ix["currentShortPositionQuantity"]]); prev = num(f[ix["previousShortPositionQuantity"]] or 0)
                adv = num(f[ix["averageDailyVolumeQuantity"]] or 0)
                if not sym or cur < 0:
                    continue
                d = {"date": f[ix["settlementDate"]][:10], "shares": int(cur)}
                if adv > 0:
                    d["avgVol"] = int(adv); d["dtc"] = round(cur / adv, 2)
                if prev > 0:
                    d["prev"] = int(prev); d["changePct"] = round((cur / prev - 1) * 100, 1)
                out[sym] = d
            except (ValueError, KeyError, IndexError):
                continue
        if len(out) > 1000:
            return out
    return {}


def screener_rows():
    j = json.loads(get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", NQ, timeout=60))
    return (j.get("data") or {}).get("rows") or []


def shares_outstanding(rows=None):
    """{SYMBOL: shares} from market cap / last sale."""
    out = {}
    for r in rows if rows is not None else screener_rows():
        try:
            cap, last = num(r.get("marketCap") or 0), num(r.get("lastsale") or 0)
            if cap > 0 and last > 0:
                out[(r.get("symbol") or "").strip().replace("/", ".")] = cap / last
        except ValueError:
            pass
    return out


def short_for(t, finra, shares):
    """Short-interest record for one ticker, with % of shares outstanding when both numbers are known."""
    s = finra.get(t) or finra.get(t.replace(".", "")) or finra.get(t.replace(".", "-"))
    if not s:
        return None
    s = dict(s)
    so = shares.get(t)
    if so and 0 < s["shares"] / so < 0.9:
        s["pctOut"] = round(s["shares"] / so * 100, 2)
    return s
