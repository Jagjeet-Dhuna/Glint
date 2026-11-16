"""Snip application controller: tray icon, hotkeys, capture flow, windows."""
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QTimer, QUrl, Qt
from PySide6.QtGui import QCursor, QDesktopServices, QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import settings as settings_mod
from . import storage, theme, winapi

INSTANCE_KEY = "Snip-single-instance-" + os.environ.get("USERNAME", "user")
HK_PRIMARY, HK_SECONDARY, HK_INSTANT, HK_REPEAT = 1, 2, 3, 4
HK_ALL = (HK_PRIMARY, HK_SECONDARY, HK_INSTANT, HK_REPEAT)


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        try:
            et = bytes(event_type.data()) if hasattr(event_type, "data") else bytes(event_type)
            if et == b"windows_generic_MSG":
                hk = winapi.hotkey_id_from_msg(message)
                if hk is not None:
                    QTimer.singleShot(0, lambda: self.callback(hk))
                    return True, 0
        except Exception:
            pass
        return False, 0


class SnipApp(QObject):
    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.settings = settings_mod.Settings()
        self.editors = []
        self.pins = []
        self.quick = None
        self.session = None
        self.scroller = None
        self._cursor = QPoint(0, 0)

        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        self.tray.setToolTip("Glint")
        menu = QMenu()
        menu.addAction("New capture", self.start_capture)
        menu.addAction("Full screen", lambda: self.start_capture("fullscreen"))
        menu.addAction("All screens", lambda: self.start_capture("all"))
        menu.addAction("Scrolling capture", lambda: self.start_capture("scroll"))
        menu.addAction("Grab text", lambda: self.start_capture("text"))
        self.repeat_action = menu.addAction("Repeat last area", self.repeat_last)
        self.repeat_action.setEnabled(bool(self.settings.last_region))
        dm = menu.addMenu("Delayed capture")
        for sec in (3, 5, 10):
            dm.addAction(f"{sec} seconds", lambda sec=sec: self.start_capture(delay=sec))
        menu.addSeparator()
        menu.addAction("New from clipboard", self.new_from_clipboard)
        self.unpin_action = menu.addAction("Unpin all", self.close_pins)
        self.unpin_action.setVisible(False)
        self.clickable_action = menu.addAction("Make pins clickable again", self.pins_interactive)
        self.clickable_action.setVisible(False)
        menu.addAction("Open Glint", self.show_home)
        menu.addAction("Open captures folder",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.save_folder)))
        menu.addSeparator()
        menu.addAction("Quit Glint", self.quit)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.show_home)
        self.tray.show()

        self.hotkeys = HotkeyFilter(self._on_hotkey)
        qapp.installNativeEventFilter(self.hotkeys)
        self.register_hotkeys(show_errors=True)

        from .home import HomeWindow
        self.home = HomeWindow(self)
        theme.follow_system(QApplication.instance(), self.theme_changed)

        from .capture import grabber
        QTimer.singleShot(300, grabber.warm_up)  # first capture is instant
        from .indexer import TextIndexer
        self.indexer = TextIndexer(self.settings)
        self.indexer.updated.connect(lambda: self.home.library.refresh_text())
        QTimer.singleShot(4000, self.indexer.scan)
        QTimer.singleShot(1200, self._check_printscreen)
        QTimer.singleShot(2500, self._stamp_shortcuts)

        self.server = QLocalServer(self)
        QLocalServer.removeServer(INSTANCE_KEY)
        self.server.listen(INSTANCE_KEY)
        self.server.newConnection.connect(self._on_instance_msg)

    # ---------------------------------------------------------------- plumbing
    def theme_changed(self):
        """Light/dark switched: rebuild what has colours baked into pixmaps (library thumbnails)."""
        try:
            self.home.library.cards_box.refresh_colors()
            self.home.refresh()
        except Exception:
            pass

    def register_hotkeys(self, show_errors=False):
        for hid in HK_ALL:
            winapi.unregister_hotkey(hid)
        failed = []
        s = self.settings
        for hid, name in ((HK_PRIMARY, s.hotkey_primary), (HK_SECONDARY, s.hotkey_secondary),
                          (HK_INSTANT, s.hotkey_instant), (HK_REPEAT, s.hotkey_repeat)):
            if not winapi.register_hotkey(hid, name):
                failed.append(name)
        if failed and show_errors:
            self.tray.showMessage("Glint", f"Hotkey {', '.join(failed)} is used by another app. "
                                          "Pick another in Settings.", QSystemTrayIcon.Warning, 6000)
        return not failed

    def _on_hotkey(self, hid):
        if hid in (HK_PRIMARY, HK_SECONDARY):
            if self.scroller is not None:
                self.scroller.stop()  # pressing the capture key again finishes a scrolling capture
            else:
                self.start_capture()
        elif hid == HK_INSTANT:
            self.instant_capture()
        elif hid == HK_REPEAT:
            self.repeat_last()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.start_capture()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_home()

    def _on_instance_msg(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return

        def read():
            cmd = bytes(sock.readAll()).decode("utf-8", "ignore").strip()
            sock.disconnectFromServer()
            if cmd == "capture":
                self.start_capture()
            elif cmd == "quit":      # sent by the installer before it replaces files
                self.quit()
            elif cmd != "background":
                self.show_home()

        sock.readyRead.connect(read)

    def _stamp_shortcuts(self):
        try:
            from .install import stamp_own_shortcuts
            stamp_own_shortcuts()
        except Exception:
            pass
        if self.settings.start_with_windows:
            try:
                winapi.ensure_start_with_windows()
            except Exception:
                pass

    def _check_printscreen(self):
        s = self.settings
        uses = "Print Screen" in (s.hotkey_primary, s.hotkey_secondary)
        if not uses or not winapi.printscreen_owned_by_windows():
            return
        if s.asked_printscreen:
            return
        s.set(asked_printscreen=True)
        r = QMessageBox.question(None, "Glint", "Windows is using the Print Screen key to open Snipping Tool.\n\n"
                                 "Let Glint use Print Screen instead?")
        if r == QMessageBox.Yes:
            try:
                winapi.release_printscreen_from_windows()
                self.register_hotkeys()
            except Exception:
                pass

    def last_cursor_pos(self):
        return QCursor.pos()

    def show_home(self):
        self.home.refresh()
        self.home.showNormal()
        self.home.raise_()
        self.home.activateWindow()
        winapi.force_foreground(self.home.winId())

    def library_changed(self):
        if self.home.isVisible():
            self.home.refresh()
        if hasattr(self, "indexer"):
            self.indexer.scan()

    def quit(self):
        for e in list(self.editors):
            e.close()
            if e.isVisible():
                return
        for hid in HK_ALL:
            winapi.unregister_hotkey(hid)
        self.indexer.stop()
        self.tray.hide()
        self.qapp.quit()

    # ---------------------------------------------------------------- capture flow
    def start_capture(self, mode="region", delay=0, hide_home=False):
        if self.session is not None or self.scroller is not None:
            return
        wait = 0
        if self.quick is not None:
            try:
                self.quick.dismiss()
            except RuntimeError:
                pass
            self.quick = None
            wait = 150
        if hide_home and self.home.isVisible():
            self.home.hide()
            wait = 300
        if self._menu.isVisible():
            self._menu.hide()
            wait = max(wait, 150)
        if delay:
            self.tray.showMessage("Glint", f"Capturing in {delay} seconds…", QSystemTrayIcon.Information, 1500)
        QTimer.singleShot(wait + delay * 1000, lambda: self._begin(mode))

    def _begin(self, mode):
        from .overlay import CaptureSession
        if self.session is not None:
            return
        s = self.settings
        try:
            self.session = CaptureSession(mode, last_region=s.last_region, window_style=s.window_style,
                                          hide_icons=s.hide_desktop_icons and mode != "scroll")
        except Exception as e:
            self.session = None
            self.tray.showMessage("Glint", f"Capture failed: {e}", QSystemTrayIcon.Critical, 5000)
            return
        self.session.finished.connect(self._session_finished)
        self.session.cancelled.connect(self._capture_ended)
        self.session.message.connect(lambda m: self.tray.showMessage("Glint", m, QSystemTrayIcon.Information, 2000))
        self.session.start()

    def instant_capture(self):
        """Capture the active window - or the whole monitor if it's a fullscreen/borderless game -
        with no overlay, so a fullscreen game never loses focus."""
        from PySide6.QtCore import QRect
        from .capture import grabber
        if self.session is not None:
            return
        try:
            full, vx, vy = grabber.grab()
            fg = winapi.foreground_window()
            mons = [QRect(l, t, r - l, b - t) for _, (l, t, r, b) in winapi.monitors()]
            info, rect = {}, None
            if fg and fg["cls"] not in ("Progman", "WorkerW", "Shell_TrayWnd"):
                l, t, r, b = fg["rect"]
                rect = QRect(l, t, r - l, b - t)
                info = {"title": fg["title"], "app": fg["app"], "exe": "", "hwnd": fg["hwnd"]}
                for m in mons:
                    if m.intersected(rect).size() == m.size():  # covers a monitor: fullscreen / borderless
                        rect = m
                        break
            if rect is None:
                cx, cy = winapi.cursor_pos()
                rect = next((m for m in mons if m.contains(cx, cy)), mons[0])
            img = full.copy(rect.translated(-vx, -vy).intersected(full.rect()))
        except Exception as e:
            self.tray.showMessage("Glint", f"Capture failed: {e}", QSystemTrayIcon.Critical, 4000)
            return
        if img.isNull():
            return
        self._captured(img, info, quiet=True)

    def _remember_region(self, rect):
        if rect is not None and rect.width() > 2 and rect.height() > 2:
            self.settings.set(last_region=[rect.x(), rect.y(), rect.width(), rect.height()])
            self.repeat_action.setEnabled(True)

    def repeat_last(self):
        """Capture the same screen area as last time, straight away (no overlay)."""
        from PySide6.QtCore import QRect
        from .capture import grabber
        r = self.settings.last_region
        if not r:
            self.tray.showMessage("Glint", "Nothing to repeat yet - take a capture first.",
                                  QSystemTrayIcon.Information, 2000)
            return
        if self.session is not None or self.scroller is not None:
            return
        try:
            full, vx, vy = grabber.grab()
            rect = QRect(*r)
            img = full.copy(rect.translated(-vx, -vy).intersected(full.rect()))
            c = rect.center()
            w = next((w for w in winapi.list_windows()
                      if w["rect"][0] <= c.x() < w["rect"][2] and w["rect"][1] <= c.y() < w["rect"][3]), None)
            info = {"title": w["title"], "app": w["app"], "exe": "", "hwnd": w["hwnd"]} if w else {}
        except Exception as e:
            self.tray.showMessage("Glint", f"Capture failed: {e}", QSystemTrayIcon.Critical, 4000)
            return
        if not img.isNull():
            self._captured(img, info)

    def _session_finished(self, img, info):
        sess = self.session
        if sess is not None and sess.mode not in ("text",):
            self._remember_region(getattr(sess, "last_rect", None))
        if sess is not None and sess.mode == "text":
            self.session = None
            self.grab_text(img)
            return
        if sess is not None and sess.mode == "scroll":
            self.session = None
            # games (windowed, borderless or fullscreen) only get Manual mode: Auto would send
            # simulated scroll input, which anti-cheat can flag. Manual sends nothing.
            game = winapi.is_game((info or {}).get("hwnd"))
            from .scroll import ScrollCapture
            if not self.settings._d.get("scroll_v2"):  # one-time move to the new frozen mode
                self.settings.set(scroll_mode="freeze", scroll_v2=True)
            mode = (self.settings.scroll_mode if self.settings.scroll_mode in ("manual", "freeze")
                    else "freeze") if not game else "manual"
            self.scroller = ScrollCapture(sess.last_rect, info, mode=mode, allow_auto=not game)
            orig_set_mode = self.scroller.set_mode

            def set_mode(m):  # remember the user's choice for next time
                orig_set_mode(m)
                if not game:
                    self.settings.set(scroll_mode=self.scroller.mode)

            self.scroller.set_mode = set_mode

            def done(im, inf):
                self.scroller = None
                self._captured(im, inf)

            def failed(msg):
                self.scroller = None
                self.tray.showMessage("Glint", msg, QSystemTrayIcon.Warning, 3000)

            def cancelled():
                self.scroller = None

            self.scroller.finished.connect(done)
            self.scroller.failed.connect(failed)
            self.scroller.cancelled.connect(cancelled)
            QTimer.singleShot(150, self.scroller.start)  # let the overlay disappear first
            return
        self._captured(img, info)

    def grab_text(self, img):
        """Text mode: read the selected area and put the words on the clipboard. Nothing is saved."""
        from . import ocr
        QApplication.setOverrideCursor(Qt.BusyCursor)
        try:
            text = ocr.lines_to_text(ocr.recognize(img)).strip()
        except Exception as e:
            text = None
            self.tray.showMessage("Glint", f"Text recognition failed: {e}", QSystemTrayIcon.Warning, 4000)
        finally:
            QApplication.restoreOverrideCursor()
        if text is None:
            return
        if not text:
            from . import qr
            codes = qr.decode(img)
            if codes:
                text = "\n".join(c for c, _ in codes)
        if text:
            QApplication.clipboard().setText(text)
            n = len(text.splitlines())
            preview = text.splitlines()[0][:60]
            self.tray.showMessage("Glint", f"Copied {n} line{'s' if n != 1 else ''} of text\n{preview}",
                                  QSystemTrayIcon.Information, 2500)
        else:
            self.tray.showMessage("Glint", "No text found there", QSystemTrayIcon.Information, 2000)

    def _capture_ended(self):
        self.session = None

    def _captured(self, img, info, quiet=False):
        self.session = None
        info = dict(info or {})
        hwnd = info.pop("hwnd", None)
        info.pop("exe", None)
        if hwnd:
            from . import library
            library.save_app_icon(info.get("app"), hwnd)
        self._cursor = QCursor.pos()
        s = self.settings
        path = None
        original, hidden = img, []
        if s.auto_redact and not quiet:
            from . import redact, render
            QApplication.setOverrideCursor(Qt.BusyCursor)
            try:
                hidden = redact.auto_hide(original)
            except Exception:
                hidden = []
            finally:
                QApplication.restoreOverrideCursor()
            if hidden:
                img = render.render(original, hidden)
        if s.auto_copy:
            QApplication.clipboard().setImage(img)
        if s.auto_save:
            try:
                path = storage.new_capture_path(s.save_folder)
                if hidden:
                    storage.save_project(path, original, hidden, img)
                else:
                    storage.atomic_save(img, path)
                if info:
                    storage.save_info(path, info)
                    from datetime import datetime
                    from . import library
                    dest = library.target_for(s, info, datetime.now())
                    if dest is not None:
                        path = library.move_capture(path, dest)
            except Exception as e:
                path = None
                self.tray.showMessage("Glint", f"Could not save capture: {e}", QSystemTrayIcon.Warning, 5000)
        self.library_changed()
        if quiet:
            # Instant capture: no window pops up over the game - just a system notification.
            name = (info.get("app") or "screen").removesuffix(".exe")
            self.tray.showMessage("Glint", f"Captured {name}" + (" · copied" if s.auto_copy else ""),
                                  QSystemTrayIcon.Information, 1500)
            return
        if s.after_capture == "editor":
            if path:
                self.open_editor(path=path)
            else:
                self.open_editor(image=original, info=info, shapes=hidden)
        elif s.after_capture == "thumbnail":
            from .quick import QuickPanel
            self.quick = QuickPanel(self, img, path, original=original, hidden=hidden)
            self.quick.destroyed.connect(lambda *_: setattr(self, "quick", None))
            self.quick.show()
        else:
            self.tray.showMessage("Glint", "Capture copied to clipboard" if s.auto_copy else "Capture saved",
                                  QSystemTrayIcon.Information, 1500)

    # ---------------------------------------------------------------- windows
    def open_editor(self, path=None, image=None, info=None, shapes=None):
        from .editor import EditorWindow
        if path:
            for e in self.editors:
                if e.path and Path(e.path) == Path(path):
                    e.showNormal()
                    e.raise_()
                    e.activateWindow()
                    return e
        if path is None and (image is None or image.isNull()):
            return None
        e = EditorWindow(self, path=path, image=image, info=info, shapes=shapes)
        self.editors.append(e)
        e.show()
        e.raise_()
        e.activateWindow()
        winapi.force_foreground(e.winId())
        return e

    def editor_closed(self, e):
        if e in self.editors:
            self.editors.remove(e)

    def _pin_gone(self, w):
        if w in self.pins:
            self.pins.remove(w)
        self.pins_changed()
        self.unpin_action.setVisible(bool(self.pins))
        self.unpin_action.setText(f"Unpin all ({len(self.pins)})")
        cb = getattr(w, "on_close", None)
        if cb:
            cb()

    def pins_changed(self):
        self.clickable_action.setVisible(any(w.click_through for w in self.pins))

    def pins_interactive(self):
        for w in list(self.pins):
            if w.click_through:
                w.set_click_through(False)
        self.pins_changed()

    def new_from_clipboard(self):
        """Turn whatever image is on the clipboard into a new capture (saved to the library)."""
        md = QApplication.clipboard().mimeData()
        img = None
        if md is not None and md.hasImage():
            img = QImage(md.imageData())
        elif md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile() and not QImage(u.toLocalFile()).isNull():
                    img = QImage(u.toLocalFile())
                    break
        if img is None or img.isNull():
            self.tray.showMessage("Glint", "There's no image on the clipboard.", QSystemTrayIcon.Information, 2500)
            return
        img = img.convertToFormat(QImage.Format_RGB32)
        path = None
        if self.settings.auto_save:
            try:
                path = storage.new_capture_path(self.settings.save_folder)
                storage.atomic_save(img, path)
                storage.save_info(path, {"app": "", "title": "Pasted image"})
            except Exception:
                path = None
        self.library_changed()
        if path:
            self.open_editor(path=path)
        else:
            self.open_editor(image=img)

    def close_pins(self):
        for w in list(self.pins):
            w.close()

    def _pin_for(self, key):
        for w in self.pins:
            if w.key is not None and w.key == key:
                return w
        return None

    def is_pinned(self, key):
        return self._pin_for(key) is not None

    def unpin(self, key):
        w = self._pin_for(key)
        if w:
            w.close()

    def pin_image(self, img, key=None, on_close=None):
        """Pin an image. The same source (editor / file / image) is only ever pinned once -
        pinning it again just brings the existing pin forward."""
        from .pin import PinWindow
        if key is None and img is not None:
            key = ("img", img.cacheKey())
        existing = self._pin_for(key)
        if existing:
            existing.raise_()
            existing.activateWindow()
            existing.flash()
            return existing
        w = PinWindow(self, img)
        w.key = key
        w.on_close = on_close
        self.pins.append(w)
        w.destroyed.connect(lambda *_: self._pin_gone(w))
        self.unpin_action.setVisible(True)
        self.unpin_action.setText(f"Unpin all ({len(self.pins)})")
        w.show()
        w.activateWindow()
        return w


def _install_crash_log():
    log = settings_mod.APP_DIR / "snip.log"

    def hook(t, v, tb):
        try:
            settings_mod.APP_DIR.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(t, v, tb)) + "\n")
        except Exception:
            pass
        sys.__excepthook__(t, v, tb)

    sys.excepthook = hook


def _selftest(out):
    from PySide6.QtGui import QColor, QFont, QPainter
    report = []

    def check(name, fn):
        try:
            report.append(f"{name}: OK {fn()}")
        except Exception as e:
            report.append(f"{name}: FAIL {type(e).__name__}: {e}")

    img = QImage(400, 80, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    f = QFont("Segoe UI")
    f.setPixelSize(28)
    p.setFont(f)
    p.setPen(QColor("black"))
    p.drawText(10, 50, "Hello Glint 123")
    p.end()
    from . import ocr, qr
    check("ocr", lambda: ocr.lines_to_text(ocr.recognize(img)))
    check("qr", lambda: qr.decode(img))
    check("uia", lambda: __import__("snip.uia", fromlist=["_init"])._init() is not None)
    check("capture", lambda: (lambda r: (r[0].width(), r[0].height()))(__import__(
        "snip.capture", fromlist=["grabber"]).grabber.grab()))
    check("icon", lambda: not theme.app_icon().isNull())

    def modules():
        import importlib
        import pkgutil
        import snip
        names = [m.name for m in pkgutil.iter_modules(snip.__path__)]
        for n in names:
            importlib.import_module(f"snip.{n}")
        return len(names)
    check("modules", modules)

    def stamps_and_combine():
        from . import combine, render
        shapes = [{"kind": "stamp", "pts": [[10, 10], [60, 60]], "text": "✅", "color": "#ff3b30", "width": 4},
                  {"kind": "stamp", "pts": [[80, 10], [160, 40]], "text": "BUG", "color": "#ff3b30", "width": 4}]
        out = render.render(img, shapes)
        both = combine.combine([out, img], "row", 8, "white")
        return f"{both.width()}x{both.height()}"
    check("stamps+combine", stamps_and_combine)
    text = "\n".join(report)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


def main():
    _install_crash_log()
    args = sys.argv[1:]
    cmd = "capture" if "--capture" in args else ("background" if "--background" in args else "show")

    # Own taskbar identity, so Windows shows Glint's icon instead of Python's.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Glint.ScreenCapture")
    except Exception:
        pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("Glint")
    if "--selftest" in args:   # packaging check: exercises the native parts, writes a report, exits
        return _selftest(args[args.index("--selftest") + 1] if len(args) > args.index("--selftest") + 1 else "")
    if "--install" in args or "--uninstall" in args:
        from . import install
        theme.apply_theme(qapp)
        qapp.setWindowIcon(theme.app_icon())
        return install.install() if "--install" in args else install.uninstall()
    qapp.setQuitOnLastWindowClosed(False)

    # Already running? Hand the command to the running copy and exit.
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(cmd.encode())
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return 0

    from .settings import Settings
    _s = Settings()
    theme.apply_theme(qapp, _s.accent, _s.appearance)
    qapp.setWindowIcon(theme.app_icon())
    app = SnipApp(qapp)
    if cmd == "capture":
        QTimer.singleShot(200, app.start_capture)
    elif cmd == "show":
        app.show_home()
    if app.settings.first_run:
        app.settings.set(first_run=False)
        QTimer.singleShot(800, lambda: app.tray.showMessage(
            "Glint is running",
            f"Press {app.settings.hotkey_primary} or {app.settings.hotkey_secondary} to capture. "
            "Glint lives in the tray — click its icon to capture.",
            QSystemTrayIcon.Information, 7000))
    return qapp.exec()
