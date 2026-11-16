"""Capture files on disk.

Every capture is a plain PNG in the save folder. If it has annotations, the un-annotated
base image and the shape list live in a hidden ".snip" folder next to it, so edits can be
reopened and changed later.
"""
import json
import threading
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFile
from PySide6.QtGui import QImage

from . import winapi

META = ".snip"


def meta_paths(path):
    p = Path(path)
    m = p.parent / META
    return m / (p.stem + ".base.png"), m / (p.stem + ".json")


def atomic_save(img, path):
    """Write PNG to a temp file, verify it, then swap it in. Never leaves a 0-byte file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if not img.save(str(tmp), "PNG"):
        raise OSError(f"Could not write {tmp}")
    if tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise OSError(f"Wrote an empty file for {path}")
    os.replace(tmp, path)


def new_capture_path(folder):
    stamp = datetime.now().strftime("Glint %Y-%m-%d %H-%M-%S")
    p = Path(folder) / f"{stamp}.png"
    i = 2
    while p.exists():
        p = Path(folder) / f"{stamp} ({i}).png"
        i += 1
    return p


def _read_json(jp):
    try:
        with open(jp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_json_lock = threading.RLock()  # the text indexer writes sidecars from a background thread


def _update_json(path, **fields):
    _, jp = meta_paths(path)
    with _json_lock:
        jp.parent.mkdir(parents=True, exist_ok=True)
        winapi.hide_file(jp.parent)
        data = _read_json(jp)
        data.setdefault("version", 1)
        data.update(fields)
        _write_json(jp, data)


def save_info(path, info):
    _update_json(path, info=info)


def set_tags(path, tags):
    clean = sorted({t.strip().lstrip("#").strip() for t in tags if t and t.strip().lstrip("#").strip()},
                   key=str.lower)
    _update_json(path, tags=clean)


def save_text(path, text):
    """Searchable text found in the (saved, already-censored) image."""
    _update_json(path, text=text, text_mtime=Path(path).stat().st_mtime)


def read_meta(path):
    with _json_lock:
        return _read_json(meta_paths(path)[1])


def _write_json(jp, data):
    tmp = jp.with_name(jp.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, jp)


def save_project(path, base, shapes, final, frame=None):
    """Save the flattened PNG plus (if annotated / framed) the editable sidecar."""
    bp, jp = meta_paths(path)
    with _json_lock:
        atomic_save(final, path)
        bp.parent.mkdir(parents=True, exist_ok=True)
        winapi.hide_file(bp.parent)
        data = _read_json(jp)
        data["version"] = 1
        data["shapes"] = shapes
        data["frame"] = frame
        data.pop("text", None)  # image changed - re-index text
        if shapes or frame:
            atomic_save(base, bp)
            data["has_base"] = True
        else:
            data["has_base"] = False
            bp.unlink(missing_ok=True)
        _write_json(jp, data)


def load_project(path):
    """Returns (base_image, shapes, info)."""
    bp, jp = meta_paths(path)
    data = read_meta(path)
    info = data.get("info", {})
    if data.get("has_base") and bp.exists():
        base = QImage(str(bp))
        if not base.isNull():
            return base, data.get("shapes", []), info
    return QImage(str(path)), [], info


def unhide(path):
    """Remove auto/manual 'hide sensitive info' blurs from a saved capture. Returns True if changed."""
    from .render import render
    base, shapes, _ = load_project(path)
    rest = [s for s in shapes if not s.get("redact")]
    if len(rest) == len(shapes):
        return False
    frame = read_meta(path).get("frame")
    save_project(path, base, rest, render(base, rest, frame), frame)
    return True


def delete_capture(path):
    path = Path(path)
    if not QFile.moveToTrash(str(path)):
        path.unlink(missing_ok=True)
    for p in meta_paths(path):
        p.unlink(missing_ok=True)


def list_captures(folder, limit=2000):
    """Captures in the save folder and its (non-hidden) sub-folders."""
    root = Path(folder)
    files = []
    try:
        dirs = [root] + [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        for d in dirs:
            files.extend(p for p in d.glob("*.png") if p.is_file())
    except Exception:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def info_for(path):
    return _read_json(meta_paths(path)[1]).get("info", {})
