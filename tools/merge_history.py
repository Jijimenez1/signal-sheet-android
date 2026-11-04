"""Merge the GitHub price feed (docs/data/history.json) into exported Signal Sheet price docs.

Usage: python3 -I tools/merge_history.py EXPORT_PRICES_DIR docs/data/history.json OUT_DIR
EXPORT_PRICES_DIR holds <TICKER>.json price docs exported from the Claude version.
For every ticker in the feed, writes OUT_DIR/<TICKER>.json only when the merged doc is newer
(more days, a later last day, or a different quote). Rows are combined by date (feed wins),
the last 300 kept; the quote takes the feed's values but keeps fields the feed lacks (P/E).
Prints one line per changed ticker: "<TICKER> new" or "<TICKER> update".
"""
import json, pathlib, sys

exp, hist, out = (pathlib.Path(a) for a in sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
feed = json.loads(hist.read_text()).get("tickers", {})
for t, x in sorted(feed.items()):
    f = exp / f"{t}.json"
    cur = json.loads(f.read_text()) if f.exists() else None
    old = cur or {"t": t, "rows": []}
    m = {d: c for d, c in old.get("rows", [])}
    m.update({d: c for d, c in x.get("rows", [])})
    rows = [[d, m[d]] for d in sorted(m)][-300:]
    quote = dict(old.get("quote") or {})
    quote.update(x.get("quote") or {})
    doc = dict(old, t=t, rows=rows, quote=quote, source=x.get("source", old.get("source", "")), updated=x.get("fetched", old.get("updated")))
    oq = old.get("quote") or {}
    changed = (len(rows) != len(old.get("rows", [])) or (rows and old.get("rows") and rows[-1] != old["rows"][-1])
               or oq.get("price") != quote.get("price") or not old.get("rows"))
    if changed:
        (out / f"{t}.json").write_text(json.dumps(doc, separators=(",", ":")))
        print(t, "new" if cur is None else "update")
