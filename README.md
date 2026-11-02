# Signal Sheet for Android

A small Android app that opens your Signal Sheet full-screen. It uses Chrome under the hood, so your Claude sign-in carries over and the weekly picks, watchlist and chart lab all work.

## Build the APK (no computer needed)

1. Create a free account at github.com and make a new repository (e.g. `signal-sheet-android`).
2. Upload everything in this folder to the repository, keeping the folder structure (including `.github/workflows`).
3. Open the **Actions** tab. The "Build Signal Sheet APK" job starts on its own (or tap **Run workflow**). It takes about 3–5 minutes.
4. When it finishes, open the run and download **SignalSheet-apk** under Artifacts. Unzip it to get `app-debug.apk`.

## Install on your phone

1. Open `app-debug.apk` on your Android phone.
2. If asked, allow your browser or file app to "install unknown apps".
3. Tap **Install**, then open **Signal Sheet** from your app drawer.
4. The first time, sign in to Claude if prompted.

## Notes

- Chrome needs to be installed (it is on most Android phones).
- A thin address bar may show at the top. That's Android's safety check for apps that open a website they don't own; everything works the same.
- The app always loads the live page, so weekly updates show up automatically. There's nothing to reinstall.
