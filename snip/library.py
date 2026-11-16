"""Folders and auto-sort rules.

Folders are real sub-folders of the save folder (visible in Explorer). Each folder may carry a rule;
new captures that match a rule are filed into that folder automatically.

rule = {"apps": ["Discord", ...], "title": "keyword", "from": "YYYY-MM-DD" | None, "to": ... | None}
"""
import re
import shutil
from datetime import date
from pathlib import Path

from . import storage, winapi

APP_NAMES = {"code": "VS Code", "steamwebhelper": "Steam", "msedge": "Edge", "chrome": "Chrome",
             "firefox": "Firefox", "explorer": "File Explorer", "applicationframehost": "Windows app",
             "windowsterminal": "Terminal", "devenv": "Visual Studio", "winword": "Word", "excel": "Excel",
             "powerpnt": "PowerPoint", "outlook": "Outlook", "olk": "Outlook", "ms-teams": "Teams",
             "notepad": "Notepad", "spotify": "Spotify", "obs64": "OBS", "javaw": "Minecraft"}


def pretty_app(exe_name, title=""):
    base = re.sub(r"\.exe$", "", exe_name or "", flags=re.I)
    if not base:
        return ""
    if base.lower() in ("pythonw", "python") and (title or "").startswith("Glint"):
        return "Glint"               # older captures of Glint's own windows
    return APP_NAMES.get(base.lower(), base[:1].upper() + base[1:])


def clean_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (name or "").strip()).strip(". ")
    return name[:60]


def folder_dirs(root):
    try:
        return sorted((p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def has_conditions(rule):
    return bool(rule) and bool(rule.get("apps") or (rule.get("title") or "").strip()
                               or rule.get("from") or rule.get("to"))


def rule_matches(rule, app, title, ts):
    if not has_conditions(rule):
        return False
    apps = rule.get("apps") or []
    kw = (rule.get("title") or "").strip().lower()
    if apps and app not in apps:
        return False
    if kw and kw not in (title or "").lower():
        return False
    d = ts.date()
    try:
        if rule.get("from") and d < date.fromisoformat(rule["from"]):
            return False
        if rule.get("to") and d > date.fromisoformat(rule["to"]):
            return False
    except ValueError:
        return False
    return True


def describe(rule):
    if not has_conditions(rule):
        return ""
    parts = []
    if rule.get("apps"):
        parts.append(", ".join(rule["apps"]))
    if (rule.get("title") or "").strip():
        parts.append(f"title has “{rule['title'].strip()}”")
    f, t = rule.get("from"), rule.get("to")
    fmt = lambda s: date.fromisoformat(s).strftime("%b %d, %Y").replace(" 0", " ")  # noqa: E731
    if f and t:
        parts.append(f"{fmt(f)} – {fmt(t)}")
    elif f:
        parts.append(f"from {fmt(f)}")
    elif t:
        parts.append(f"until {fmt(t)}")
    return "  ·  ".join(parts)


def target_for(settings, info, ts):
    """Folder path a new capture should be filed into, or None."""
    app = pretty_app((info or {}).get("app"))
    title = (info or {}).get("title", "")
    root = Path(settings.save_folder)
    for name, rule in (settings.folder_rules or {}).items():
        if (root / name).is_dir() and rule_matches(rule, app, title, ts):
            return root / name
    return None


def move_capture(path, dest_dir):
    """Move a capture (and its editable sidecars) into dest_dir. Returns the new path."""
    path, dest = Path(path), Path(dest_dir)
    if path.parent.resolve() == dest.resolve():
        return path
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / path.name
    i = 2
    while target.exists():
        target = dest / f"{path.stem} ({i}){path.suffix}"
        i += 1
    old_b, old_j = storage.meta_paths(path)
    new_b, new_j = storage.meta_paths(target)
    shutil.move(str(path), str(target))
    for a, b in ((old_b, new_b), (old_j, new_j)):
        if a.exists():
            b.parent.mkdir(parents=True, exist_ok=True)
            winapi.hide_file(b.parent)
            shutil.move(str(a), str(b))
    return target


def remove_folder(root, name):
    """Move a folder's captures back to the root, then delete the folder if nothing else is in it."""
    d = Path(root) / name
    for p in d.glob("*.png"):
        move_capture(p, root)
    meta = d / storage.META
    if meta.is_dir() and not any(meta.iterdir()):
        meta.rmdir()
    try:
        d.rmdir()
    except OSError:
        pass  # user put other files in it - leave it alone


def icon_path(app_name):
    from .settings import APP_DIR
    return APP_DIR / "icons" / f"{clean_name(app_name) or 'app'}.png"


def save_app_icon(exe_name, hwnd):
    """Cache the captured app's icon (read from its window, never from the process)."""
    app = pretty_app(exe_name)
    if not app or not hwnd:
        return
    p = icon_path(app)
    if p.exists():
        return
    try:
        from PySide6.QtGui import QImage
        h = winapi.window_icon(hwnd)
        if h:
            img = QImage.fromHICON(h)
            if not img.isNull():
                p.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(p), "PNG")
    except Exception:
        pass
