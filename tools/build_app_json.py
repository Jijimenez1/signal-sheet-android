"""Assemble docs/data/app.json for the public app from an ArtifactData export folder.
Usage: python3 -I tools/build_app_json.py EXPORT_DIR
EXPORT_DIR holds weeks/, prices/ and signals/ folders of <id>.json files,
as written by ArtifactData list/get with out_dir."""
import sys, json, pathlib, datetime
root = pathlib.Path(sys.argv[1])
def docs(name):
    d = root / name
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}
weeks = sorted(docs("weeks").values(), key=lambda w: w.get("weekOf", ""), reverse=True)[:8]
sig = docs("signals").get("latest")
# The owner's watchlist is private: never publish it, its scores, or prices for
# tickers that appear only on it. Only stocks on the weekly list or Strong buys go out.
public = {p.get("t") for w in weeks for p in w.get("picks", [])}
public |= {p.get("t") for p in (sig or {}).get("picks", [])}
app = {
    "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "weeks": weeks,
    "prices": {k: v for k, v in docs("prices").items() if k in public},
    "signals": sig,
}
if not weeks:
    sys.exit("No weeks found in export; refusing to publish an empty app.json")
out = pathlib.Path("docs/data/app.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app, separators=(",", ":")))
print(f"wrote {out}: {len(weeks)} weeks, {len(app['prices'])} price docs, signals={'yes' if sig else 'no'}, {out.stat().st_size} bytes")
