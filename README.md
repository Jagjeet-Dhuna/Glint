<p align="center"><img src="assets/glint.png" width="96" alt="Glint logo"></p>

<h1 align="center">Glint</h1>

<p align="center">A fast, offline screen capture tool for Windows.</p>

Glint lives in the tray and replaces the Snipping Tool. It does area, window and full-screen captures,
scrolling captures, text grabs and game captures, and includes an editor and a searchable library.
Everything runs on your PC. There are no accounts, no cloud and no AI services.

## Install

1. Download `Glint.zip` from the [latest release](https://github.com/Jagjeet-Dhuna/Glint/releases/latest).
2. Extract it anywhere, then double-click **Install Glint.cmd**.

Glint is copied to `%LOCALAPPDATA%\Programs\Glint`, gets Start menu and desktop shortcuts, and starts in
the tray. No admin rights are needed, and you can delete the extracted folder afterwards.

To uninstall, run **Uninstall Glint.cmd** from `%LOCALAPPDATA%\Programs\Glint`. Your captures and settings are kept.

> Glint is not code-signed, so it ships as a zip with its own Python runtime rather than a setup.exe.
> Only signed files run (python.org's `pythonw.exe` and Qt's DLLs), so it works with Smart App Control on.

## Shortcuts

| Key | Action |
| --- | --- |
| `Print Screen` | Capture: drag an area, click a window, or press Space for the whole screen |
| `Ctrl+Shift+X` | Second capture shortcut |
| `Ctrl+Print Screen` | Instant capture with no overlay, for games |

In the capture overlay you can also press `S` for a scrolling capture, `T` to grab text, `R` to repeat the
last area, `M` to measure, and `C` to copy the colour under the cursor. You can change all shortcuts in
Settings.

## Features

**Capture**
- Area, window and screen captures, with correct results on mixed-DPI multi-monitor setups.
- Window captures with clean rounded corners or a shadow, plus an option to hide desktop icons.
- Scrolling capture. Glint freezes the page, then you scroll the frozen picture (Manual) or let Glint step
  to the end (Auto). It copes with playing videos, hover previews and sticky headers.
- Timer captures (3, 5 or 10 s), and repeat last area.
- Instant game capture that works in windowed, borderless and exclusive fullscreen.
- Grab text with the built-in Windows OCR. QR codes and barcodes are detected automatically.

**Editor**
- Arrows (tapered, classic, double or curved), shapes, lines, text, callouts and text boxes.
- Stamps, blur and pixelate (click a line of text to hide it), spotlight and magnify.
- Colour picker with a loupe, measure tool, and a pixel grid when zoomed in.
- Beautify: padding, backgrounds and rounded corners.
- Auto-hide sensitive info (optional), always with an **Unhide** button.
- Copy as a data URI, base64, Markdown, HTML or a file path. Resize the image.

**Library**
- Folders with auto-sort rules (by app, title keyword or date).
- Tags, and search that includes the text inside your captures.
- Sorting, box and keyboard selection, a duplicate finder, and combining captures into one image.
- A storage bar split by folder.
- System, Day and Night themes with a choice of accent colours.

## Privacy and games

- Fully offline: Glint makes no network requests.
- Anti-cheat safe: Glint never opens handles to other processes, injects code, installs hooks, or sends
  input to games.

## Run from source

Requires Windows 10/11 and Python 3.12.

```
pip install PySide6 numpy dxcam comtypes zxing-cpp winrt-runtime "winrt-Windows.Foundation" "winrt-Windows.Foundation.Collections" "winrt-Windows.Globalization" "winrt-Windows.Graphics.Imaging" "winrt-Windows.Media.Ocr" "winrt-Windows.Storage.Streams"
pythonw Glint.pyw
```

Run the tests with `python tests/run_all.py`. They run offline and never touch real windows.

To build the zip, run `pip install pyinstaller`, then `python packaging/build.py`. The output is `dist/Glint.zip`.

## Credits

The interface uses [IBM Plex](https://github.com/IBM/plex) fonts under the SIL Open Font License
(`assets/fonts/LICENSE.txt`).
