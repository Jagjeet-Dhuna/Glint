import os
import sys
import os, sys, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, home, storage
theme.apply_theme(app, appearance="dark")
lib_dir = os.path.join(OUT, "fake_lib"); shutil.rmtree(lib_dir, ignore_errors=True); os.makedirs(lib_dir)
for i, (w, h, c) in enumerate([(800, 500, "#d33"), (600, 600, "#3a3"), (1000, 400, "#33d"), (500, 700, "#dd3")]):
    im = QImage(w, h, QImage.Format_RGB32); im.fill(QColor(c)); im.save(os.path.join(lib_dir, f"cap{i}.png"))
class St(settings.Settings):
    def save(self): pass
class A:
    settings = St(); opened = []
    def is_pinned(self, w): return False
    def open_editor(self, **kw): A.opened.append(kw)
    def __getattr__(self, n): return lambda *a, **k: None
A.settings._d["save_folder"] = lib_dir; A.settings._d["library_sort"] = "name"
w = home.HomeWindow(A()); w.resize(1100, 760); w.show(); w.refresh(); QTest.qWait(200)
lib = w.library; paths = sorted(lib.tiles)
def ok(n, c): print(("PASS " if c else "FAIL ") + n)
d = home.TagDialog(lib, paths[:2]); d.edit.setText("work, #bug"); d._save(); QTest.qWait(50)
d = home.TagDialog(lib, paths[1:3]); d.edit.setText("receipts"); d._save(); QTest.qWait(50)
tags = {os.path.basename(p): storage.read_meta(p).get("tags") for p in paths}
print(" ", tags)
ok("tags saved", tags["cap0.png"] == ["bug", "work"] and tags["cap1.png"] == ["bug", "receipts", "work"] and tags["cap2.png"] == ["receipts"])
navs = [b.text() for b in w.tag_navs]; print("  sidebar:", navs)
ok("sidebar lists tags + Untagged", navs[:3] == ["#bug", "#receipts", "#work"] and "Untagged" in navs[-1])
w._set_filter(("tag", "work"), "#work"); ok("filter #work -> 2", len(lib.tiles) == 2)
w._set_filter(("untagged", None), "Untagged"); ok("Untagged -> 1", len(lib.tiles) == 1)
w._set_filter(("all", None), "Home"); lib.search.setText("#receipts"); lib.rebuild(); ok("search #receipts -> 2", len(lib.tiles) == 2)
lib.search.setText(""); lib.rebuild()
# removing: open dialog on cap1 (has bug,receipts,work), uncheck 'bug'
d = home.TagDialog(lib, [paths[1]]); d.buttons["bug"].setChecked(False); d._save()
ok("untick removes", storage.read_meta(paths[1]).get("tags") == ["receipts", "work"])
# partial tags untouched: cap0 has bug,work; cap2 has receipts. dialog on both, save without clicks
d = home.TagDialog(lib, [paths[0], paths[2]]); d._save()
ok("partial tags kept", storage.read_meta(paths[0]).get("tags") == ["bug", "work"] and storage.read_meta(paths[2]).get("tags") == ["receipts"])
QTest.qWait(300); print("  visible tiles:", sum(t.isVisible() for t in lib.tiles.values()), "tag buttons visible:", sum(b.isVisible() for b in w.tag_navs)); w.grab().save(OUT + "/tags_home.png")
# combine
c = home.CombineDialog(lib, paths); c.show(); QTest.qWait(50)
for lay in ("row", "column", "grid"):
    c.layout_cb.setCurrentIndex(c.layout_cb.findData(lay)); im = c.result()
    print(f"  {lay}: {im.width()}x{im.height()} alpha={im.hasAlphaChannel()}")
c.layout_cb.setCurrentIndex(0); c.bg_cb.setCurrentIndex(2); c.round_cb.setChecked(True); QTest.qWait(50)
c.grab().save(OUT + "/combine.png"); c._open()
ok("combined opens in editor", A.opened and not A.opened[0]["image"].isNull())
