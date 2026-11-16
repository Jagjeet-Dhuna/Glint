"""Background text index: reads the text in every capture (Windows OCR, offline) so the library
search can find words *inside* screenshots. Text is read from the saved PNG, so anything that
was hidden as sensitive is never indexed."""
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import storage


class TextIndexer(QObject):
    updated = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._queue = []
        self._queued = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self.done = 0
        threading.Thread(target=self._run, daemon=True, name="glint-indexer").start()

    def scan(self):
        """Queue every capture whose text is missing or out of date."""
        def work():
            for p in storage.list_captures(self.settings.save_folder):
                try:
                    meta = storage.read_meta(p)
                    if "text" in meta and meta.get("text_mtime") == p.stat().st_mtime:
                        continue
                except OSError:
                    continue
                self.add(p)
        threading.Thread(target=work, daemon=True).start()

    def add(self, path):
        path = str(path)
        with self._lock:
            if path in self._queued:
                return
            self._queued.add(path)
            self._queue.append(path)
        self._wake.set()

    def stop(self):
        self._stop = True
        self._wake.set()

    def _run(self):
        from . import ocr
        batch = 0
        while not self._stop:
            with self._lock:
                path = self._queue.pop(0) if self._queue else None
                if path:
                    self._queued.discard(path)
            if path is None:
                if batch:
                    self.updated.emit()
                    batch = 0
                self._wake.wait()
                self._wake.clear()
                continue
            try:
                p = Path(path)
                if p.exists():
                    img = QImage(path)
                    if not img.isNull():
                        text = ocr.lines_to_text(ocr.recognize(img))
                        if p.exists():
                            storage.save_text(p, text)
                            self.done += 1
                            batch += 1
            except Exception:
                pass
            if batch >= 10:
                self.updated.emit()
                batch = 0
            time.sleep(0.03)  # stay light on the CPU
