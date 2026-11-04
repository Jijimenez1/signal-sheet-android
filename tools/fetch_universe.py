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
from fetch_prices import get, num, NQ, valid, make_quote, KEEP  # noqa: E402

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
            name = (r.get("name") or sym).replace(" Common Stock", "").replace(" Class A Ordinary Shares", "").strip()
            out[sym] = (name, cap)
    return out


def history(t, etf):
    start = (dt.date.today() - dt.timedelta(days=430)).isoformat()
    for cls in (("etf", "stocks") if etf else ("stocks", "etf")):
        try:
            j = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass={cls}&fromdate={start}&limit=9999", NQ))
        except Exception:
            continue
        rows = {}
        for r in ((j.get("data") or {}).get("tradesTable") or {}).get("rows") or []:
            try:
                m, d, y = r["date"].split("/")
                rows[f"{y}-{m}-{d}"] = round(num(r["close"]), 4)
            except (ValueError, KeyError):
                pass
        if rows:
            return sorted(rows.items())
    return None


def one(t, name, etf, out, now):
    for attempt in range(3):
        rows = history(t, etf)
        if rows:
            break
        time.sleep(2 + attempt * 3)
    if not rows:
        return t, "no data"
    why = valid(rows)
    if why:
        return t, why
    quote, rows = make_quote(rows[-KEEP:], None, now)
    doc = {"t": t, "name": name, "source": "Nasdaq", "rows": [[d, round(c, 4)] for d, c in rows[-KEEP:]], "quote": quote,
           "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    (out / "px" / f"{t}.json").write_text(json.dumps(doc, separators=(",", ":")))
    return t, None


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "universe-out")
    (out / "px").mkdir(parents=True, exist_ok=True)
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    now = dt.datetime.now(dt.timezone.utc)
    stocks = screener()
    print(f"screener: {len(stocks)} stocks with market cap >= ${MIN_CAP/1e9:.0f}B")
    if len(stocks) < 200:
        sys.exit("Screener returned too few stocks; not publishing.")
    items = sorted(stocks.items(), key=lambda kv: -kv[1][1])
    jobs = [(t, n, True) for t, n in ETFS.items()] + [(t, n, False) for t, (n, _) in items if t not in ETFS]
    if limit:
        jobs = jobs[:limit]
    names, fails = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(one, t, n, e, out, now): (t, n) for t, n, e in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            t, n = futs[f]
            try:
                _, err = f.result()
            except Exception as e:
                err = str(e)[:80]
            if err:
                fails.append(f"{t}: {err}")
            else:
                names[t] = n
            if i % 250 == 0:
                print(f"{i}/{len(jobs)} done, {len(fails)} failed, {time.time()-t0:.0f}s")
    print(f"{len(names)} tickers written, {len(fails)} failed")
    print("\n".join(fails[:60]))
    if len(names) < 0.8 * len(jobs):
        sys.exit("Too many failures; not publishing.")
    (out / "universe.json").write_text(json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tickers": dict(sorted(names.items()))}, separators=(",", ":")))


if __name__ == "__main__":
    main()
