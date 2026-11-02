"""Build the public, no-sign-in Signal Sheet page (docs/index.html) from the Claude version.
Usage: python3 tools/build_page.py path/to/signal-sheet.html
The public page reads data/app.json (written by tools/build_app_json.py) through a tiny
stand-in for the Claude data API, so the app code stays identical. Owner-only controls stay hidden."""
import sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
shim = r"""<script>
/* Public data source: data/app.json on GitHub Pages, refreshed every 5 minutes. Read-only. */
(function(){
  let APP=null; const subs=[];
  const docsOf=(arr)=>({metadata:{fromCache:false,hasPendingWrites:false},docs:arr,size:arr.length,empty:!arr.length,docChanges:()=>[]});
  const D=(id,v)=>({id,exists:true,data:()=>v,metadata:{fromCache:false}});
  function coll(p){
    if(!APP) return [];
    if(p==="weeks") return (APP.weeks||[]).slice().sort((a,b)=>b.weekOf<a.weekOf?-1:1).map(w=>D(w.weekOf,w));
    if(p==="prices") return Object.keys(APP.prices||{}).map(k=>D(k,APP.prices[k]));
    if(p==="wlscores") return Object.keys(APP.wlscores||{}).map(k=>D(k,APP.wlscores[k]));
    if(p==="watchlist") return (APP.watchlist||[]).map(t=>D(t,{ticker:t}));
    return [];
  }
  function one(p){ if(APP&&p==="signals/latest"&&APP.signals) return D("latest",APP.signals); return {id:p.split("/").pop(),exists:false,data:()=>undefined,metadata:{fromCache:false}}; }
  function push(){ subs.forEach(s=>{ try{ s.kind==="c"?s.cb(docsOf(coll(s.p))):s.cb(one(s.p)); }catch(e){} }); }
  async function load(){ try{ const r=await fetch("data/app.json?t="+Date.now(),{cache:"no-store"}); if(r.ok){ APP=await r.json(); push(); } }catch(e){} }
  const q=p=>({orderBy(){return this},limit(){return this},where(){return this},onSnapshot(cb){ const s={kind:"c",p,cb}; subs.push(s); if(APP) setTimeout(()=>cb(docsOf(coll(p))),0); return()=>{}; },get:async()=>docsOf(coll(p))});
  const db={collection:q,doc:p=>({onSnapshot(cb){ const s={kind:"d",p,cb}; subs.push(s); if(APP) setTimeout(()=>cb(one(p)),0); return()=>{}; },get:async()=>one(p),set:async()=>{throw{code:"invalid_argument"}},update:async()=>{throw{code:"invalid_argument"}},delete:async()=>{throw{code:"invalid_argument"}}})};
  window.claude={use:async n=>n==="db"?db:n==="user"?{isOwner:()=>false,canEdit:()=>false,can:()=>false}:null};
  window.SS_PUBLIC={reload:load};
  load(); setInterval(load,5*60*1000);
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden) load(); });
})();
</script>
"""
page = src
# public wording
page = page.replace('<li>They need a free Claude account to sign in.</li>', '<li>No account or sign-in needed. It opens straight to the picks.</li>')
page = page.replace('<li id="shareOwnerStep">Give them access: on claude.ai, open Signal Sheet, tap <b>Share</b>, and add their email as a Viewer.</li>', '')
page = page.replace('<p>iPhone users: open the Signal Sheet link in Safari, tap Share, then Add to Home Screen.</p>', '<p>iPhone users: open <b>jijimenez1.github.io/signal-sheet-android</b> in Safari, tap Share, then Add to Home Screen.</p>')
head = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icon.svg">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head><body>"""
out = head + shim + page + "\n</body></html>\n"
pathlib.Path("docs/index.html").write_text(out)
print("wrote docs/index.html", len(out), "bytes")
