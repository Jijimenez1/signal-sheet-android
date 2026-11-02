# Signal Sheet

Weekly stock odds, Strong buys, a watchlist and technical analysis. No account or sign-in needed.

- **Android app:** https://github.com/Jijimenez1/signal-sheet-android/releases/latest (tap **SignalSheet.apk**, then Install; allow "install unknown apps" if asked)
- **Web / iPhone:** https://jijimenez1.github.io/signal-sheet-android/ (on iPhone: Safari, Share, Add to Home Screen)

Estimates from public data. Not financial advice.

## How it works

- `docs/` is the public site (GitHub Pages). `docs/data/app.json` holds the data and is republished automatically after each update.
- `tools/build_page.py` builds `docs/index.html` from the Claude version of the page; `tools/build_app_json.py` builds `app.json` from a data export.
- `app/` is a small Android WebView app that opens the public site. Every push to `main` that touches `app/` builds a signed APK and publishes it as the latest release.
