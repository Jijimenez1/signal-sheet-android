"""Assemble docs/data/app.json for the public app from an ArtifactData export folder.
Usage: python3 -I tools/build_app_json.py EXPORT_DIR
EXPORT_DIR holds weeks/, prices/, wlscores/, watchlist/ and signals/ folders of <id>.json files,
as written by ArtifactData list/get with out_dir."""
import sys, json, pathlib, datetime
root = pathlib.Path(sys.argv[1])
def docs(name):
    d = root / name
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}
weeks = sorted(docs("weeks").values(), key=lambda w: w.get("weekOf", ""), reverse=True)[:8]
sig = docs("signals").get("latest")
app = {
    "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "weeks": weeks,
    "prices": docs("prices"),
    "wlscores": {k: v for k, v in docs("wlscores").items()},
    "watchlist": sorted(docs("watchlist").keys()),
    "signals": sig,
}
if not weeks:
    sys.exit("No weeks found in export; refusing to publish an empty app.json")
out = pathlib.Path("docs/data/app.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app, separators=(",", ":")))
print(f"wrote {out}: {len(weeks)} weeks, {len(app['prices'])} price docs, {len(app['watchlist'])} watchlist, signals={'yes' if sig else 'no'}, {out.stat().st_size} bytes")
