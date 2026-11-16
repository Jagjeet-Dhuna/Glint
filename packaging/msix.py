"""Build the Microsoft Store package:   python packaging/build.py   then   python packaging/msix.py

Output: dist/Glint.msix  ->  upload in Partner Center. The Store signs it, so users get no warnings.

Uses the same runtime/ + app/ folders as the zip (dist/Glint), plus:
- runtime/python3XX._pth so Python finds Glint without depending on the working folder
  (packaged apps start in System32) and the package launches with "-m snip".
- .pyc files compiled up front: the install folder is read-only, so Python couldn't cache them.
- Tile/taskbar icons drawn from assets/glint.png, and an AppxManifest.xml with a startup task.

Identity (name/publisher) comes from packaging/store.json. Tools: makeappx.exe + makepri.exe from the
Windows SDK, or the Microsoft.Windows.SDK.BuildTools NuGet package; set SDK_BIN to their folder.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "Glint"
STAGE = ROOT / "build" / "msix"
OUT = ROOT / "dist" / "Glint.msix"
STARTUP_TASK = "GlintStartup"   # must match winapi.STARTUP_TASK


def find_tool(name):
    for d in filter(None, [os.environ.get("SDK_BIN")]):
        if (Path(d) / name).exists():
            return str(Path(d) / name)
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    hits = sorted(kits.glob(f"*/x64/{name}")) if kits.exists() else []
    if hits:
        return str(hits[-1])
    found = shutil.which(name)
    if found:
        return found
    sys.exit(f"Can't find {name}. Install the Windows SDK or set SDK_BIN to the folder that has it.")


def draw_assets(dest):
    """Store/tile/taskbar images from the app logo."""
    from PySide6.QtCore import Qt, QRect
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    QGuiApplication.instance() or QGuiApplication(["x"])
    logo = QImage(str(ROOT / "assets" / "glint.png"))

    def save(name, w, h, frac=1.0):
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        side = int(min(w, h) * frac)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRect((w - side) // 2, (h - side) // 2, side, side), logo)
        p.end()
        img.save(str(dest / name))

    dest.mkdir(parents=True, exist_ok=True)
    for scale in (100, 125, 150, 200, 400):
        k = scale / 100
        save(f"Square44x44Logo.scale-{scale}.png", round(44 * k), round(44 * k))
        save(f"Square150x150Logo.scale-{scale}.png", round(150 * k), round(150 * k), 0.6)
        save(f"Wide310x150Logo.scale-{scale}.png", round(310 * k), round(150 * k), 0.6)
        save(f"SmallTile.scale-{scale}.png", round(71 * k), round(71 * k), 0.7)
        save(f"LargeTile.scale-{scale}.png", round(310 * k), round(310 * k), 0.5)
        save(f"StoreLogo.scale-{scale}.png", round(50 * k), round(50 * k))
    for t in (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256):
        save(f"Square44x44Logo.targetsize-{t}.png", t, t)
        save(f"Square44x44Logo.targetsize-{t}_altform-unplated.png", t, t)
        save(f"Square44x44Logo.targetsize-{t}_altform-lightunplated.png", t, t)


MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap10 desktop rescap">
  <Identity Name="{name}" Publisher="{publisher}" Version="{version}" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>{display_name}</DisplayName>
    <PublisherDisplayName>{publisher_display_name}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Resources>
    <Resource Language="en-us"/>
  </Resources>
  <Applications>
    <Application Id="Glint" Executable="runtime\\pythonw.exe" uap10:Parameters="-m snip"
                 EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{display_name}" Description="Offline screen capture for Windows"
                          BackgroundColor="transparent"
                          Square150x150Logo="Assets\\Square150x150Logo.png" Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" Square71x71Logo="Assets\\SmallTile.png"
                         Square310x310Logo="Assets\\LargeTile.png"/>
      </uap:VisualElements>
      <Extensions>
        <desktop:Extension Category="windows.startupTask" Executable="runtime\\pythonw.exe"
                           uap10:Parameters="-m snip --background" EntryPoint="Windows.FullTrustApplication">
          <desktop:StartupTask TaskId="{startup}" Enabled="true" DisplayName="{display_name}"/>
        </desktop:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust"/>
  </Capabilities>
</Package>
"""


def main():
    if not (SRC / "runtime" / "pythonw.exe").exists():
        sys.exit("Run packaging/build.py first (it makes dist/Glint).")
    ident = json.loads((ROOT / "packaging" / "store.json").read_text(encoding="utf-8"))
    makeappx, makepri = find_tool("makeappx.exe"), find_tool("makepri.exe")

    shutil.rmtree(STAGE, ignore_errors=True)
    shutil.copytree(SRC / "runtime", STAGE / "runtime")
    shutil.copytree(SRC / "app", STAGE / "app")
    v = f"{sys.version_info[0]}{sys.version_info[1]}"
    (STAGE / "runtime" / f"python{v}._pth").write_text(
        "Lib\nLib\\site-packages\nDLLs\n..\\app\nimport site\n", encoding="ascii")
    subprocess.check_call([sys.executable, "-m", "compileall", "-q", "-j", "0",
                           "--invalidation-mode", "unchecked-hash", str(STAGE)])
    draw_assets(STAGE / "Assets")
    (STAGE / "AppxManifest.xml").write_text(
        MANIFEST.format(startup=STARTUP_TASK, **{k: ident[k] for k in
                        ("name", "publisher", "publisher_display_name", "display_name", "version")}), encoding="utf-8")

    cfg = ROOT / "build" / "priconfig.xml"
    subprocess.check_call([makepri, "createconfig", "/cf", str(cfg), "/dq", "en-US", "/pv", "10.0.0", "/o"],
                          stdout=subprocess.DEVNULL)
    subprocess.check_call([makepri, "new", "/pr", str(STAGE), "/cf", str(cfg),
                           "/of", str(STAGE / "resources.pri"), "/o"], stdout=subprocess.DEVNULL)
    OUT.unlink(missing_ok=True)
    subprocess.check_call([makeappx, "pack", "/d", str(STAGE), "/p", str(OUT), "/o"], stdout=subprocess.DEVNULL)
    print(f"Built {OUT} ({OUT.stat().st_size / 1e6:.0f} MB) as {ident['name']} {ident['version']}")


if __name__ == "__main__":
    main()
