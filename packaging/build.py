"""Build Glint for other PCs:   python packaging/build.py

Output: dist/Glint.zip  ->  extract anywhere on the other PC, double-click "Install Glint.cmd".

Why not a setup.exe: Windows 11's Smart App Control blocks unsigned .exe files, and a code-signing
certificate costs money. This package only runs signed files (python.org's pythonw.exe, Qt's DLLs),
exactly like Glint runs on this PC, so it works with Smart App Control on.

Steps:
1. PyInstaller analyses Glint to find which Qt files it really uses (94 MB of PySide6's 650 MB).
2. A private copy of this Python (runtime/) gets the standard library + only the packages Glint needs.
3. Glint's source goes in app/, plus Install / Uninstall launchers, then everything is zipped.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
OUT = DIST / "Glint"
PY = Path(sys.base_prefix)
SITE = PY / "Lib" / "site-packages"

PACKAGES = ["shiboken6", "numpy", "numpy.libs", "dxcam", "comtypes", "winrt", "zxingcpp", "typing_extensions"]
SKIP_LIB = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "__pycache__",
            "venv", "pydoc_data"}
SKIP_DLLS = {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll"}


def analyse_qt():
    """Let PyInstaller work out which PySide6 binaries/plugins Glint needs."""
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "GlintScan",
        "--distpath", str(BUILD / "scan"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--log-level", "WARN", str(ROOT / "Glint.pyw")], cwd=ROOT)
    scanned = BUILD / "scan" / "GlintScan" / "_internal" / "PySide6"
    return {p.relative_to(scanned) for p in scanned.rglob("*") if p.is_file()}


def copytree(src, dst, skip=()):
    shutil.copytree(src, dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", *skip))


def build_runtime(qt_files):
    rt = OUT / "runtime"
    (rt / "Lib").mkdir(parents=True, exist_ok=True)
    for f in ("python.exe", "pythonw.exe", "python3.dll", f"python{sys.version_info[0]}{sys.version_info[1]}.dll",
              "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        if (PY / f).exists():
            shutil.copy2(PY / f, rt / f)
    (rt / "DLLs").mkdir(exist_ok=True)
    for f in (PY / "DLLs").iterdir():
        if f.is_file() and f.name not in SKIP_DLLS:
            shutil.copy2(f, rt / "DLLs" / f.name)
    for item in (PY / "Lib").iterdir():
        if item.name in SKIP_LIB:
            continue
        if item.is_dir():
            copytree(item, rt / "Lib" / item.name)
        else:
            shutil.copy2(item, rt / "Lib" / item.name)
    site = rt / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for name in PACKAGES:
        for src in SITE.glob(name):
            if src.is_dir():
                copytree(src, site / src.name, skip=("*.pyi", "tests", "testing"))
        for src in list(SITE.glob(name + "*.pyd")) + list(SITE.glob(name + ".py")):
            shutil.copy2(src, site / src.name)
    # PySide6: the Python glue + only the Qt binaries PyInstaller found
    pyside = SITE / "PySide6"
    for f in pyside.rglob("*.py"):
        rel = f.relative_to(pyside)
        if rel.parts[0] in ("examples", "scripts", "Qt"):
            continue
        (site / "PySide6" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, site / "PySide6" / rel)
    for rel in qt_files:
        src = pyside / rel
        if not src.exists():
            # PyInstaller renames some runtime DLLs' case; find them case-insensitively
            match = [p for p in pyside.iterdir() if p.name.lower() == rel.name.lower()] if len(rel.parts) == 1 else []
            if not match:
                continue
            src = match[0]
        dst = site / "PySide6" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def build_app():
    app = OUT / "app"
    app.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "Glint.pyw", app / "Glint.pyw")
    copytree(ROOT / "snip", app / "snip")
    copytree(ROOT / "assets", app / "assets")
    (OUT / "Install Glint.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0runtime\\pythonw.exe" "%~dp0app\\Glint.pyw" --install\r\n', encoding="ascii")
    (OUT / "Uninstall Glint.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0runtime\\pythonw.exe" "%~dp0app\\Glint.pyw" --uninstall\r\n', encoding="ascii")
    (OUT / "README.txt").write_text(
        "Glint - screen capture\r\n\r\n"
        "Install: double-click \"Install Glint.cmd\". Glint is copied to your user folder, gets Start menu and\r\n"
        "desktop shortcuts, and starts in the tray. No admin rights needed. You can delete this folder afterwards.\r\n\r\n"
        "Uninstall: run \"Uninstall Glint.cmd\" from %LOCALAPPDATA%\\Programs\\Glint. Captures and settings are kept.\r\n",
        encoding="utf-8")


def make_zip():
    z = DIST / "Glint.zip"
    z.unlink(missing_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in OUT.rglob("*"):
            if f.is_file():
                zf.write(f, Path("Glint") / f.relative_to(OUT))
    return z


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    qt = analyse_qt()
    build_runtime(qt)
    build_app()
    z = make_zip()
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"Built {OUT} ({size:.0f} MB) and {z} ({z.stat().st_size / 1e6:.0f} MB)")
