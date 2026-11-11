"""Daily price files for every popular US stock and ETF, so any ticker someone watches has a chart.

Runs on GitHub Actions (.github/workflows/universe.yml) after the close. Writes into OUT_DIR:
  universe.json      {"updated": ..., "tickers": {"AAPL": "Apple Inc.", ...}}
  px/<TICKER>.json   {"t", "name", "source", "rows": [[date, close], ...], "quote": {...}, "fetched"}
The workflow publishes OUT_DIR as the orphan "data" branch (force-pushed, so history never piles up).
The app reads them from raw.githubusercontent.com/Jijimenez1/signal-sheet-android/data/.

Universe: US-listed common stocks with a market cap of at least MIN_CAP (Nasdaq screener),
plus the ETFs in ETFS. Prices come from Nasdaq's daily history; each file is checked the same
way as the main feed (20+ closes, newest within 10 days, no zero prices).
"""
import json, pathlib, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fetch_prices import get, num, NQ, valid, make_quote, nasdaq_regular, KEEP  # noqa: E402
import re

MIN_CAP = 1e9
ETFS = {
    "SPY": "SPDR S&P 500 ETF", "VOO": "Vanguard S&P 500 ETF", "IVV": "iShares Core S&P 500 ETF",
    "VTI": "Vanguard Total Stock Market ETF", "QQQ": "Invesco QQQ Trust", "QQQM": "Invesco Nasdaq 100 ETF",
    "DIA": "SPDR Dow Jones Industrial Average ETF", "IWM": "iShares Russell 2000 ETF", "VUG": "Vanguard Growth ETF",
    "VTV": "Vanguard Value ETF", "SCHD": "Schwab US Dividend Equity ETF", "VYM": "Vanguard High Dividend Yield ETF",
    "VXUS": "Vanguard Total International Stock ETF", "VEA": "Vanguard FTSE Developed Markets ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF", "EFA": "iShares MSCI EAFE ETF", "EEM": "iShares MSCI Emerging Markets ETF",
    "BND": "Vanguard Total Bond Market ETF", "AGG": "iShares Core US Aggregate Bond ETF", "TLT": "iShares 20+ Year Treasury Bond ETF",
    "SHY": "iShares 1-3 Year Treasury Bond ETF", "HYG": "iShares iBoxx High Yield Corporate Bond ETF",
    "GLD": "SPDR Gold Shares", "IAU": "iShares Gold Trust", "SLV": "iShares Silver Trust", "USO": "United States Oil Fund",
    "XLK": "Technology Select Sector SPDR", "XLF": "Financial Select Sector SPDR", "XLE": "Energy Select Sector SPDR",
    "XLV": "Health Care Select Sector SPDR", "XLI": "Industrial Select Sector SPDR", "XLY": "Consumer Discretionary Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR", "XLU": "Utilities Select Sector SPDR", "XLB": "Materials Select Sector SPDR",
    "XLRE": "Real Estate Select Sector SPDR", "XLC": "Communication Services Select Sector SPDR",
    "SMH": "VanEck Semiconductor ETF", "SOXX": "iShares Semiconductor ETF", "ARKK": "ARK Innovation ETF",
    "IBIT": "iShares Bitcoin Trust", "FBTC": "Fidelity Wise Origin Bitcoin Fund", "ETHA": "iShares Ethereum Trust",
    "TQQQ": "ProShares UltraPro QQQ", "SQQQ": "ProShares UltraPro Short QQQ", "SOXL": "Direxion Daily Semiconductor Bull 3X",
    "JEPI": "JPMorgan Equity Premium Income ETF", "JEPQ": "JPMorgan Nasdaq Equity Premium Income ETF",
    "VGT": "Vanguard Information Technology ETF", "VNQ": "Vanguard Real Estate ETF", "RSP": "Invesco S&P 500 Equal Weight ETF",
    "SPLG": "SPDR Portfolio S&P 500 ETF", "MDY": "SPDR S&P MidCap 400 ETF", "IJH": "iShares Core S&P Mid-Cap ETF",
    "IJR": "iShares Core S&P Small-Cap ETF", "XBI": "SPDR S&P Biotech ETF", "KRE": "SPDR S&P Regional Banking ETF",
    "ITA": "iShares US Aerospace & Defense ETF", "URA": "Global X Uranium ETF", "TAN": "Invesco Solar ETF",
}


CUT = re.compile(r"\s+(Common Stock|Common Shares|Ordinary Shares|Class [A-Z]\b|American Depos|Depositary|Sponsored|Units|Unit\b|Warrant|\(The\)|New\b|\().*$", re.I)


def clean_name(n):
    n = CUT.sub("", re.sub(r"\s+", " ", n or "").strip()).strip(" ,-")
    return n


def screener():
    j = json.loads(get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", NQ, timeout=60))
    rows = (j.get("data") or {}).get("rows") or []
    out = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip().replace("/", ".").replace("^", "-")
        try:
            cap = num(r.get("marketCap") or 0)
        except ValueError:
            cap = 0
        if sym and cap >= MIN_CAP and all(c.isalnum() or c in ".-" for c in sym):
            name = clean_name(r.get("name") or sym) or sym
            try:  # regular-session last price and change, used to add today's close before history catches up
                last, chg = num(r.get("lastsale")), num(r.get("netchange"))
            except ValueError:
                last = chg = None
            out[sym] = (name, cap, last, chg)
    return out


import fetch_prices as fp  # noqa: E402

HLV = fp.HLV  # highs/lows/volume collected by the history sources


def history(t, etf):
    """Daily closes: Nasdaq first, StockAnalysis when Nasdaq is blocking GitHub's servers."""
    for fn in (fp.nasdaq, fp.stockanalysis):
        try:
            rows = fn(t)
            if rows:
                return rows
        except Exception:
            continue
    return None


SHORT = None  # set in main: ticker -> short-interest record


def one(t, name, etf, out, now, scr=None):
    for attempt in range(2):
        rows = history(t, etf)
        if rows:
            break
        time.sleep(2)
    if not rows:
        return t, "no data"
    why = valid(rows)
    if why:
        return t, why
    live = None
    if scr and scr[0] and scr[1] is not None:
        # The screener's last sale is today's regular close only if last - change matches our last close.
        if abs((scr[0] - scr[1]) / rows[-1][1] - 1) < 0.005 or abs(scr[0] / rows[-1][1] - 1) < 1e-9:
            live = (scr[0], "Closed", "")
    elif etf:
        live = fp.live_quote(t)[0]
    quote, rows = make_quote(rows[-KEEP:], live, now)
    doc = {"t": t, "name": name, "source": "Nasdaq", "rows": [[d, round(c, 4)] for d, c in rows[-KEEP:]], "quote": quote,
           "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    m = HLV.pop(t, None) or {}
    hl = [[d] + m[d] for d, _ in rows[-130:] if d in m]
    if hl:
        doc["hlv"] = hl
    sh = SHORT(t) if SHORT else None
    if sh:
        doc["short"] = sh
    (out / "px" / f"{t}.json").write_text(json.dumps(doc, separators=(",", ":")))
    return t, None


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "universe-out")
    (out / "px").mkdir(parents=True, exist_ok=True)
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    now = dt.datetime.now(dt.timezone.utc)
    try:
        stocks = screener()
        print(f"screener: {len(stocks)} stocks with market cap >= ${MIN_CAP/1e9:.0f}B")
    except Exception as e:
        stocks = {}
        print("screener unavailable:", str(e)[:100])
    if len(stocks) >= 200:
        items = sorted(stocks.items(), key=lambda kv: -kv[1][1])
        jobs = [(t, n, True, None) for t, n in ETFS.items()] + [(t, v[0], False, v[2:]) for t, v in items if t not in ETFS]
    else:
        # Nasdaq's list is unavailable: keep yesterday's list of tickers and refresh their prices from the backup source
        prev = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
        old = json.loads(prev.read_text()).get("tickers", {}) if prev and prev.exists() and prev.stat().st_size > 10 else {}
        if len(old) < 200:
            print("No ticker list available; leaving the published data as it is.")
            return
        print(f"using the previous list of {len(old)} tickers")
        jobs = [(t, n, t in ETFS, None) for t, n in old.items()]
    if limit:
        jobs = jobs[:limit]
    global SHORT
    try:
        import extras
        finra = extras.finra_short()
        try:
            shares = extras.shares_outstanding()
        except Exception:
            shares = {}
        print(f"short interest: {len(finra)} symbols")
        SHORT = lambda t: extras.short_for(t, finra, shares)
    except Exception as e:
        print("short interest skipped:", str(e)[:120])
    names, fails = {}, []
    t0 = time.time()
    BUDGET = 40 * 60  # seconds; whatever isn't fetched by then counts as failed
    ex = ThreadPoolExecutor(max_workers=4)
    if True:
        futs = {ex.submit(one, t, n, e, out, now, sc): (t, n) for t, n, e, sc in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            t, n = futs[f]
            if time.time() - t0 > BUDGET:
                print(f"time budget used up after {i} of {len(jobs)}", flush=True)
                ex.shutdown(wait=False, cancel_futures=True)
                break
            try:
                _, err = f.result()
            except Exception as e:
                err = str(e)[:80]
            if err:
                fails.append(f"{t}: {err}")
            else:
                names[t] = n
            if i % 250 == 0:
                print(f"{i}/{len(jobs)} done, {len(fails)} failed, {time.time()-t0:.0f}s, blocked: {sorted(fp.BLOCKED)}", flush=True)
    print(f"{len(names)} tickers written, {len(fails)} failed")
    print("\n".join(fails[:60]))
    if fp.BLOCKED:
        print("blocked this run:", ", ".join(sorted(fp.BLOCKED)))
    if len(names) < 0.8 * len(jobs):
        print("Too many failures; leaving the published data as it is.")
        return
    (out / "universe.json").write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": dict(sorted(names.items()))}, separators=(",", ":")))


if __name__ == "__main__":
    main()
