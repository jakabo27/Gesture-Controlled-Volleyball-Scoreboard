# Phone display (Web Bluetooth)

A single static page that shows the live score on a phone over Bluetooth LE: no Wi-Fi, no app install. It talks to [`pi/scoreboard_link.py`](../pi/scoreboard_link.py) and draws the same digits the scoreboard is showing, in the same team colors.

**Live:** https://jakabo27.github.io/Gesture-Controlled-Volleyball-Scoreboard/ (deployed from `main` by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml)). Add `?demo` to see it without a scoreboard.

## What it shows

* **Bold seven-segment digits.** The glyphs come from the Arduino (the digits it actually drew), so tennis mode's `Ad` / `dE uc` show up exactly as on the board.
* **Team colors:** the colors come from the scoreboard's color sliders, converted with a port of FastLED's `hsv2rgb_rainbow`, so they match the LEDs. White and rainbow are supported. Rainbow digits sweep the hue along each segment in the direction the LEDs are wired.
* **Day theme** (default): a white page with the team color darkened just enough for ~4.5:1 contrast against white. Colored light on black washes out in direct sun, and dark-on-white at full brightness doesn't.
* **Night theme:** black page with the team color brightened just enough to stand out, plus a soft glow. Switch with the sun / moon button.
* **Colored background** (optional): each half is filled with its team color, with black or white digits, whichever has more contrast.
* **Mirrored by default:** the phone sits on top of the scoreboard facing the person *behind* it, so AWAY is on the left and HOME on the right. Settings → "In front of the scoreboard" flips it.
* **+ / − score buttons** under each team (a big +, a small −). They run the same code as the scoreboard's own buttons; hide them in Settings.
* **T-Pose Detection switch** (top bar): turns the Pi's gesture scoring off/on, e.g. if false positives show up in a game. The camera keeps seeing and recording gestures, but they no longer change the score. It is always on after a boot.
* **Game clock** (top bar): starts at the first point after 0–0, freezes when the game is won, resets at 0–0. A `~` means you connected mid-game, so the start is approximate.
* A banner for each point ("HOME +1 · T-pose"), the game-to score, and a warning when data stops.
* **Scoreboard settings** (top of Settings): sport (volleyball / tennis, with a confirmation because it resets the score) volleyball game-to (15 / 21 / 25) and **Sound** (Effects = the usual sounds, Voice = says "Point home" / "Point away", Tones = plain beeps). These are sent to the Arduino through the Pi's command characteristic. The buttons show what the scoreboard reports, so they also reflect changes made with the physical button chords.

Display settings are stored per phone in `localStorage`.

## Connecting

1. Open the page in **Chrome on Android** (Web Bluetooth needs Chrome and https).
2. Tap **Connect** and pick **Scoreboard**. Bluetooth starts about 20s after the Pi boots, so allow ~30s after switching the scoreboard on.
3. Dropouts reconnect automatically. Reopening the page needs one tap on Connect. With Chrome's `chrome://flags/#enable-web-bluetooth-new-permissions-backend` enabled, it reconnects to the remembered scoreboard by itself.

**Add to home screen** for a full-screen app. The service worker caches the page so it opens without signal at the courts. Bump `CACHE` in `sw.js` when you change the files.

## Files

| File | |
|---|---|
| `index.html`, `style.css`, `app.js` | The page |
| `protocol.js` | BLE packet decoder, the digit table and FastLED color math, shared with the tests |
| `sw.js`, `manifest.webmanifest`, `icon*` | Offline cache and install metadata (icons drawn by `tools/make_web_icons.py`) |

## Local preview

```bash
python -m http.server 8777 --directory web
```

Then open http://127.0.0.1:8777/?demo. Web Bluetooth also works on `localhost` in desktop Chrome if the PC has Bluetooth.
