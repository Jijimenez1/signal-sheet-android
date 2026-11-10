"""Build the public, no-sign-in Signal Sheet page (docs/index.html) from the Claude version.
Usage: python3 tools/build_page.py path/to/signal-sheet.html
The public page reads data/app.json (written by tools/build_app_json.py) through a tiny
stand-in for the Claude data API, so the app code stays identical. Owner-only controls stay hidden."""
import sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
shim = r"""<script>
/* Public data source: data/app.json on GitHub Pages, refreshed every 5 minutes. Read-only, except
   the watchlist, which lives only in this phone's storage (never sent anywhere). */
(function(){
  let APP=null, lastOk=null, UNI=null; const subs=[], WL_KEY="ss_watchlist_v1", PX={}, MISS={};
  /* Daily price files for any popular US stock or ETF (built each evening by universe.yml) */
  const DATA="https://raw.githubusercontent.com/Jijimenez1/signal-sheet-android/data/";
  const wlGet=()=>{ try{ const v=JSON.parse(localStorage.getItem(WL_KEY)||"[]"); return Array.isArray(v)?v.filter(x=>typeof x==="string"):[]; }catch(e){ return []; } };
  const wlSet=a=>{ try{ localStorage.setItem(WL_KEY,JSON.stringify(a)); }catch(e){} };
  const docsOf=(arr)=>({metadata:{fromCache:false,hasPendingWrites:false},docs:arr,size:arr.length,empty:!arr.length,docChanges:()=>[]});
  const D=(id,v)=>({id,exists:true,data:()=>v,metadata:{fromCache:false}});
  function coll(p){
    if(p==="watchlist") return wlGet().map(t=>D(t,{ticker:t}));
    if(!APP) return [];
    if(p==="weeks") return (APP.weeks||[]).slice().sort((a,b)=>b.weekOf<a.weekOf?-1:1).map(w=>D(w.weekOf,w));
    if(p==="prices"){ const m=Object.assign({},PX,APP.prices||{}); for(const k in PX){ if(m[k]!==PX[k]&&!m[k].name) m[k]=Object.assign({},m[k],{name:PX[k].name}); }
      for(const k in LONG){ if(m[k]&&LONG[k]) m[k]=Object.assign({},m[k],{long:LONG[k]}); }
      return Object.keys(m).map(k=>D(k,m[k])); }
    return [];
  }
  function one(p){ if(APP&&p==="signals/latest"&&APP.signals) return D("latest",APP.signals); return {id:p.split("/").pop(),exists:false,data:()=>undefined,metadata:{fromCache:false}}; }
  function push(only){ subs.forEach(s=>{ if(only&&s.p!==only) return; try{ s.kind==="c"?s.cb(docsOf(coll(s.p))):s.cb(one(s.p)); }catch(e){} }); }
  /* Price history from the GitHub price feed (data/history.json) is merged over app.json:
     rows are combined by date, and the feed's quote wins except for fields it lacks (P/E). */
  function mergeHistory(app,h){
    if(!h||!h.tickers) return app;
    app.prices=app.prices||{};
    for(const t in h.tickers){
      const x=h.tickers[t], cur=app.prices[t]||{t,rows:[]}, m={};
      (cur.rows||[]).forEach(r=>{ m[r[0]]=r[1]; }); (x.rows||[]).forEach(r=>{ m[r[0]]=r[1]; });
      const rows=Object.keys(m).sort().slice(-300).map(d=>[d,m[d]]);
      app.prices[t]=Object.assign({},cur,{t,rows,source:x.source||cur.source,quote:Object.assign({},cur.quote||{},x.quote||{})});
      if(x.hlv) app.prices[t].hlv=x.hlv; if(x.short) app.prices[t].short=x.short;
    }
    app.updated=[app.updated,h.updated].filter(Boolean).sort().pop();
    return app;
  }
  /* Data is read straight from the repo (updates within ~5 minutes of every commit, even when
     GitHub Pages deploys are queued), falling back to this site's own copy. */
  const RAW="https://raw.githubusercontent.com/Jijimenez1/signal-sheet-android/main/docs/data/";
  async function getJSON(name){
    for(const base of [RAW,"data/"]){
      try{ const r=await fetch(base+name+"?t="+Date.now(),{cache:"no-store"}); if(r.ok) return await r.json(); }catch(e){}
    }
    return null;
  }
  /* All-time history, fetched the first time someone taps 5Y or All on a stock:
     this week's stocks come from long.json, everything else from the weekly "long" branch. */
  const LONG={}, LONGB="https://raw.githubusercontent.com/Jijimenez1/signal-sheet-android/long/long/"; let LONGALL=null;
  async function loadLong(t){
    if(LONG[t]) return true;
    try{
      if(!LONGALL){ const j=await getJSON("long.json"); if(j&&j.tickers) LONGALL=j.tickers; }
      let rows=LONGALL&&LONGALL[t]&&LONGALL[t].rows;
      if(!rows){ const r=await fetch(LONGB+encodeURIComponent(t)+".json?t="+Math.floor(Date.now()/864e5),{cache:"no-store"}); if(r.ok){ const d=await r.json(); rows=d&&d.rows; } }
      if(Array.isArray(rows)&&rows.length>1){ LONG[t]=rows; push("prices"); return true; }
    }catch(e){}
    return false;
  }
  async function loadUni(){
    try{ const r=await fetch(DATA+"universe.json?t="+Math.floor(Date.now()/36e5),{cache:"no-store"}); if(r.ok){ const u=await r.json(); if(u&&u.tickers) UNI=u; } }catch(e){}
  }
  /* Fetch price files for watchlist tickers that aren't in this week's data. */
  async function loadPx(ts,force){
    const need=ts.filter(t=>!(APP&&APP.prices&&APP.prices[t])&&(force||!PX[t]||Date.now()-PX[t]._at>30*60*1000));
    if(!need.length) return;
    await Promise.all(need.map(async t=>{
      try{ const r=await fetch(DATA+"px/"+encodeURIComponent(t)+".json?t="+Math.floor(Date.now()/6e5),{cache:"no-store"}); if(r.ok){ const d=await r.json(); if(d&&Array.isArray(d.rows)){ d._at=Date.now(); PX[t]=d; delete MISS[t]; } } else if(r.status===404) MISS[t]=1; }catch(e){}
    }));
    push("prices");
  }
  const newer=(a,b)=>!b?a:!a?b:((a.updated||"")>=(b.updated||"")?a:b);
  async function load(){
    try{
      const [a,h]=await Promise.all([getJSON("app.json"),getJSON("history.json")]);
      if(a){ let x=a; try{ if(h) x=mergeHistory(x,h); }catch(e){} APP=x; lastOk=Date.now(); push(); loadPx(wlGet(),true); if(!UNI) loadUni(); return true; }
    }catch(e){}
    return false;
  }
  const ready=p=>p==="watchlist"||APP;
  const q=p=>({orderBy(){return this},limit(){return this},where(){return this},onSnapshot(cb){ const s={kind:"c",p,cb}; subs.push(s); if(ready(p)) setTimeout(()=>cb(docsOf(coll(p))),0); return()=>{}; },get:async()=>docsOf(coll(p))});
  const deny=async()=>{ throw {code:"invalid_argument",message:"read-only"}; };
  function docRef(p){
    const m=/^watchlist\/([A-Z0-9.\-]{1,10})$/.exec(p);
    return {onSnapshot(cb){ const s={kind:"d",p,cb}; subs.push(s); if(APP) setTimeout(()=>cb(one(p)),0); return()=>{}; },get:async()=>one(p),
      set:m?async()=>{ const a=wlGet(); if(!a.includes(m[1])){ a.push(m[1]); wlSet(a); } push("watchlist"); loadPx([m[1]]); }:deny,
      update:m?async()=>{}:deny,
      delete:m?async()=>{ wlSet(wlGet().filter(x=>x!==m[1])); push("watchlist"); }:deny};
  }
  const db={collection:q,doc:docRef};
  window.claude={use:async n=>n==="db"?db:n==="user"?{isOwner:()=>false,canEdit:()=>false,can:()=>false}:null};
  window.SS_PUBLIC={reload:load,loadLong,updated:()=>APP&&APP.updated,
    /* true = we have data for this ticker, false = not a covered symbol, null = list not loaded yet */
    lookup:t=>(APP&&APP.prices&&APP.prices[t])||PX[t]?true:MISS[t]?false:UNI?(UNI.tickers[t]?null:false):null,
    nameOf:t=>(UNI&&UNI.tickers[t])||(PX[t]&&PX[t].name)||""};
  load(); setInterval(load,5*60*1000);
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden) load(); });
})();
</script>
"""
page = src
# serve the TradingView chart library from this site (vendored, Apache-2.0, see docs/vendor/)
page = page.replace("https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js", "vendor/lightweight-charts-4.1.3.standalone.js")
# public wording
page = page.replace('<li>They need a free Claude account to sign in.</li>', '<li>No account or sign-in needed. It opens straight to the picks.</li>')
import re
page = re.sub(r'<li id="shareOwnerStep">.*?</li>', '<li id="shareOwnerStep">Each person\'s watchlist stays on their own phone. Nobody else can see it.</li>', page, count=1, flags=re.S)
page = page.replace('<p>iPhone users: open the Signal Sheet link in Safari, tap Share, then Add to Home Screen.</p>', '<p>iPhone users: open <b>jijimenez1.github.io/signal-sheet-android</b> in Safari, tap Share, then Add to Home Screen.</p>')
head = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#141518" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#E9EBEE" media="(prefers-color-scheme: light)">
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icon.svg">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head><body>"""
out = head + shim + page + "\n</body></html>\n"
pathlib.Path("docs/index.html").write_text(out)
print("wrote docs/index.html", len(out), "bytes")
