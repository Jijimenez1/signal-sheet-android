"""Weekly: all-time price history for every ticker in the universe, published to the orphan "long" branch.

Usage: python3 tools/fetch_long.py UNIVERSE_JSON OUT_DIR [LIMIT]
Writes OUT_DIR/long/<TICKER>.json = {"t", "source", "rows": [[date, close], ...], "fetched"}:
monthly closes since listing plus weekly closes for the last two years (see extras.thin).
The app reads them from raw.githubusercontent.com/Jijimenez1/signal-sheet-android/long/long/<T>.json
when someone taps 5Y or All on a stock that isn't in this week's lists.
"""
import json, pathlib, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import extras  # noqa: E402
from fetch_universe import ETFS  # noqa: E402


def one(t, out, now):
    for attempt in range(2):
        rows = extras.long_history(t, etf=t in ETFS)
        if rows:
            (out / "long" / f"{t}.json").write_text(json.dumps({"t": t, "source": "StockAnalysis", "rows": rows, "fetched": now}, separators=(",", ":")))
            return None
        time.sleep(2)
    return "no data"


def main():
    uni = json.loads(pathlib.Path(sys.argv[1]).read_text())["tickers"]
    out = pathlib.Path(sys.argv[2]); (out / "long").mkdir(parents=True, exist_ok=True)
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    ts = sorted(uni)[:limit] if limit else sorted(uni)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fails, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(one, t, out, now): t for t in ts}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                err = f.result()
            except Exception as e:
                err = str(e)[:80]
            if err:
                fails.append(f"{futs[f]}: {err}")
            if i % 250 == 0:
                print(f"{i}/{len(ts)} done, {len(fails)} failed, {time.time()-t0:.0f}s")
    print(f"{len(ts)-len(fails)} written, {len(fails)} failed"); print("\n".join(fails[:40]))
    if len(fails) > 0.3 * len(ts):
        sys.exit("Too many failures; not publishing.")
    (out / "index.json").write_text(json.dumps({"updated": now, "count": len(ts) - len(fails)}))


if __name__ == "__main__":
    main()
