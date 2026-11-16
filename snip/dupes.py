"""Duplicate finder: groups captures that look the same (re-saves, repeated screenshots).

Each image gets a 64-bit difference hash (tiny greyscale thumbnail, compare neighbouring pixels).
Hashes are cached by path + modified time, so only new captures are read on later scans.
"""
import json
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QImageReader

from .settings import APP_DIR

CACHE = APP_DIR / "hashes.json"
MAX_DIST = 3   # differing bits out of 64 that still count as "the same picture"


def dhash(path):
    r = QImageReader(str(path))
    size = r.size()
    img = r.read()
    if img.isNull():
        return None
    small = img.convertToFormat(QImage.Format_Grayscale8).scaled(9, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if small.pixelColor(x, y).value() > small.pixelColor(x + 1, y).value() else 0)
    w, h = (size.width(), size.height()) if size.isValid() else (img.width(), img.height())
    return bits, w, h


def _load_cache():
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    try:
        tmp = CACHE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f)
        os.replace(tmp, CACHE)
    except Exception:
        pass


def group(entries):
    """entries: [(path, hash, w, h)] -> list of groups (lists of paths) with 2+ members."""
    n = len(entries)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        _, hi, wi, ti = entries[i]
        ari = wi / max(1, ti)
        for j in range(i + 1, n):
            _, hj, wj, tj = entries[j]
            if abs(ari - wj / max(1, tj)) > 0.02 or bin(hi ^ hj).count("1") > MAX_DIST:
                continue
            if abs(wi - wj) > max(wi, wj) * 0.05:   # same picture at very different sizes isn't a duplicate
                continue
            parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(entries[i][0])
    return [g for g in groups.values() if len(g) > 1]


class Scanner(QObject):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, paths):
        super().__init__()
        self.paths = [str(p) for p in paths]
        self.stopped = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        cache = _load_cache()
        fresh, entries = {}, []
        for i, p in enumerate(self.paths):
            if self.stopped:
                return
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            c = cache.get(p)
            if c and c[0] == mt:
                h = c[1:]
            else:
                r = dhash(p)
                if r is None:
                    continue
                h = list(r)
            fresh[p] = [mt] + list(h)
            entries.append((p, int(h[0]), int(h[1]), int(h[2])))
            if i % 10 == 0:
                self.progress.emit(i + 1, len(self.paths))
        _save_cache(fresh)
        if not self.stopped:
            self.done.emit(group(entries))
