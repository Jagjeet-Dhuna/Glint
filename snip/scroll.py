"""Scrolling capture: auto-scroll a region and stitch the frames into one tall image."""
import ctypes

import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import winapi
from .capture import grabber

user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.WindowFromPoint.argtypes = [ctypes.c_int64]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
MOUSEEVENTF_WHEEL = 0x0800
WM_MOUSEWHEEL = 0x020A
STEP = 0.45           # frozen mode: scroll this share of the view per step (leaves a big overlap to match)
MAX_HEIGHT = 30000
HK_STOP = 9


def phys_to_logical(rect):
    """Global physical QRect -> global logical QRect (handles per-monitor scaling)."""
    c = rect.center()
    for s in QGuiApplication.screens():
        g, dpr = s.geometry(), s.devicePixelRatio()
        native = QRect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr))
        if native.contains(c):
            return QRect(round(g.x() + (rect.x() - g.x()) / dpr), round(g.y() + (rect.y() - g.y()) / dpr),
                         round(rect.width() / dpr), round(rect.height() / dpr))
    return QRect(rect)


def to_array(img):
    img = img.convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    return a.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4).copy()


class Feat:
    """Frame fingerprint.
    sig - per-row signature (mean brightness in column buckets), used to *search* quickly.
    g   - half-resolution greyscale, used to *verify* a match pixel by pixel (rejects look-alikes)."""
    __slots__ = ("sig", "g")

    def __init__(self, arr, bins=96):
        g = arr[..., :3].mean(axis=2, dtype=np.float32)
        h, w = g.shape
        b = max(1, min(bins, w))
        w2 = (w // b) * b
        self.sig = g[:, :w2].reshape(h, b, -1).mean(axis=2)
        self.g = g[:, ::2]

    def __len__(self):
        return len(self.sig)


def features(arr):
    return Feat(arr)


def fdiff(a, b):
    """How different two frames are (0 = identical)."""
    return float(np.abs(a.sig - b.sig).mean())


TILE = 24          # tile size (rows x half-res columns) for voting
TILE_TEXTURE = 5.0  # a tile needs at least this much contrast (std) to have a say
TILE_WRONG = 0.02   # a tile "agrees" if fewer than 2% of its pixels clearly differ
STRICT = 0.2        # max share of disagreeing tiles when tracking (known animation is ignored)
RESYNC = 0.1        # even stricter when re-finding our place after losing track


def _vote(a, b, ignore=None):
    """Compare two equally-sized greyscale areas tile by tile.
    Returns (agree, disagree): counts of informative tiles that match exactly / don't.
    Blank tiles don't vote, and neither do tiles marked in `ignore` (known animation: a playing
    video, GIF, blinking cursor...)."""
    n, m = a.shape
    n2, m2 = (n // TILE) * TILE, (m // TILE) * TILE
    if n2 < TILE or m2 < TILE:
        return 0, 0
    a, b = a[:n2, :m2], b[:n2, :m2]
    shape = (n2 // TILE, TILE, m2 // TILE, TILE)
    wrong = (np.abs(a - b) > 32).reshape(shape).mean(axis=(1, 3))
    ta = a.reshape(shape).std(axis=(1, 3))
    tb = b.reshape(shape).std(axis=(1, 3))
    informative = (ta > TILE_TEXTURE) | (tb > TILE_TEXTURE)
    if ignore is not None:
        informative &= ~ignore[:n2, :m2].reshape(shape).any(axis=(1, 3))
    agree = int((informative & (wrong < TILE_WRONG)).sum())
    return agree, int(informative.sum()) - agree


def looks_still(a, b, ignore=None):
    """Positive evidence that the page did NOT scroll between frames a and b (same size).
    True if (nearly) everything matches in place, or if what changed forms ONE compact block
    (a playing video) with exact matches all around it. After a real scroll the changes are
    scattered over the whole page instead."""
    n, m = a.g.shape
    n2, m2 = (n // TILE) * TILE, (m // TILE) * TILE
    if n2 < TILE or m2 < TILE:
        return False
    shape = (n2 // TILE, TILE, m2 // TILE, TILE)
    A, B = a.g[:n2, :m2], b.g[:n2, :m2]
    wrong = (np.abs(A - B) > 32).reshape(shape).mean(axis=(1, 3))
    inf = (A.reshape(shape).std(axis=(1, 3)) > TILE_TEXTURE) | (B.reshape(shape).std(axis=(1, 3)) > TILE_TEXTURE)
    if ignore is not None:
        inf &= ~ignore[:n2, :m2].reshape(shape).any(axis=(1, 3))
    dis = inf & (wrong >= TILE_WRONG)
    agr = inf & (wrong < TILE_WRONG)
    d, a_ = int(dis.sum()), int(agr.sum())
    if d == 0:
        return a_ > 0 or ignore is None
    if a_ >= 4 and d <= 0.15 * (a_ + d):
        return True
    rows, cols = np.flatnonzero(dis.any(axis=1)), np.flatnonzero(dis.any(axis=0))
    box = np.zeros_like(dis)
    box[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1] = True
    inside = inf & box
    outside_agree = int((agr & ~box).sum())
    return int((dis & box).sum()) >= 0.85 * int(inside.sum()) and outside_agree >= 6


def _masked_bins(mask, r0, r1, nb):
    """Which signature columns (of nb) contain known-animated pixels in rows [r0, r1)."""
    if mask is None:
        return None
    m = mask[max(0, r0):r1].any(axis=0)
    hw = m.shape[0]
    bins = np.zeros(nb, bool)
    idx = np.flatnonzero(m) * nb // max(1, hw)
    for d in (-1, 0, 1):  # one bucket of slack either side
        bins[np.clip(idx + d, 0, nb - 1)] = True
    return bins


def _candidates(prev, new, top, bot, per_template=16, mask_prev=None, mask_new=None):
    """Fast 1-D search for plausible shifts (verified properly afterwards).
    Where a video is known (mask), its columns are left out entirely; otherwise each position is
    scored on its best-matching 70% of columns, so an unknown video can't hide the true position."""
    from numpy.lib.stride_tricks import sliding_window_view
    span = bot - top
    bh = max(12, min(64, span // 8))
    nb = prev.sig.shape[1]
    cands = set()

    def best_minima(costs, to_dy):
        mins = [i for i in range(len(costs))
                if (i == 0 or costs[i] <= costs[i - 1]) and (i == len(costs) - 1 or costs[i] <= costs[i + 1])]
        mins.sort(key=lambda i: costs[i])
        cands.update(to_dy(i) for i in mins[:per_template])

    if mask_prev is not None:
        # template from the PREVIOUS frame (where we know the video), found again higher up in the new one.
        # Scan the whole frame for bands with the most usable (textured, non-video) content - a wide
        # video can cover everything at any fixed height.
        bh = max(12, min(28, span // 16))   # thin bands fit in the gaps around a big video
        options = []
        for y1 in range(top + 4, bot - bh, max(4, bh // 2)):
            tmpl = prev.sig[y1:y1 + bh]
            bad = _masked_bins(mask_prev, y1, y1 + bh, nb)
            cols = np.flatnonzero((tmpl.std(axis=0) > 1.0) & ~bad)
            if len(cols) >= 4:
                # prefer lots of content, and lower bands (they can detect bigger scrolls)
                options.append((len(cols) * float(tmpl[:, cols].var()) * (y1 - top) ** 0.5, y1, cols))
        options.sort(key=lambda o: -o[0])
        picked = []
        for _, y1, cols in options:
            if all(abs(y1 - p) >= bh for p, _ in picked):
                picked.append((y1, cols))
            if len(picked) == 5:
                break
        for y1, cols in picked:
            max_d = y1 - top
            tmpl = prev.sig[y1:y1 + bh]
            seg = new.sig[y1 - max_d:y1 - 1 + bh][:, cols]
            wins = sliding_window_view(seg, bh, axis=0)                 # (max_d, c, bh); i -> d = max_d - i
            diff = np.abs(wins - tmpl[:, cols].T[None]).mean(axis=2)
            keep = max(3, int(len(cols) * 0.85))
            costs = np.partition(diff, keep - 1, axis=1)[:, :keep].mean(axis=1)
            best_minima(costs, lambda i, m=max_d: m - i)
        return cands

    for frac in (0.0, 0.12, 0.25, 0.4, 0.55):
        y0 = top + int(span * frac)
        best, best_v = y0, -1.0
        for yy in range(y0, max(y0 + 1, min(bot - bh, y0 + max(bh, span // 10))), 3):
            v = float(new.sig[yy:yy + bh].var())
            if v > best_v:
                best, best_v = yy, v
        y0 = best
        max_dy = bot - y0 - bh
        if best_v < 0.5 or max_dy < 1:
            continue
        tmpl = new.sig[y0:y0 + bh]                                       # (bh, nb)
        # only columns with content in this band count (blank margins match everywhere and would
        # make every shift look equally good); of those, drop the worst 30% (where a video would be)
        textured = tmpl.std(axis=0) > 1.0
        bad = _masked_bins(mask_new, y0, y0 + bh, nb)
        cols = np.flatnonzero(textured & ~bad) if bad is not None else np.flatnonzero(textured)
        if len(cols) < 4:
            continue
        keep = max(3, int(len(cols) * (0.85 if bad is not None else 0.7)))
        wins = sliding_window_view(prev.sig[y0 + 1:y0 + max_dy + bh][:, cols], bh, axis=0)  # (max_dy, c, bh)
        diff = np.abs(wins - tmpl[:, cols].T[None]).mean(axis=2)          # (max_dy, c)
        costs = np.partition(diff, keep - 1, axis=1)[:, :keep].mean(axis=1)
        mins = [i for i in range(len(costs))
                if (i == 0 or costs[i] <= costs[i - 1]) and (i == len(costs) - 1 or costs[i] <= costs[i + 1])]
        mins.sort(key=lambda i: costs[i])
        cands.update(i + 1 for i in mins[:per_template])
    return cands


def find_shift(prev, new, max_rho=0.75, ignore_prev=None, ignore_new=None, hint=None):
    """How many rows the content moved UP from `prev` to `new`. Returns (dy, agree) or (None, agree).
    dy == 0 means the page didn't scroll (even if a video on it is playing)."""
    h = len(prev)
    gp, gn = prev.g, new.g
    m2 = (gp.shape[1] // TILE) * TILE
    tc = m2 // TILE

    def integral(mask):
        if mask is None:
            return None
        s = np.zeros((h + 1, m2 + 1), np.int32)
        s[1:, 1:] = mask[:, :m2].cumsum(0).cumsum(1)
        return s

    Ip, In = integral(ignore_prev), integral(ignore_new)

    def tiles_hit(s, r0, nt):
        """Which tiles (nt rows x tc cols, starting at row r0) contain any masked pixel."""
        rs = r0 + np.arange(nt + 1) * TILE
        cs = np.arange(tc + 1) * TILE
        sub = s[np.ix_(rs, cs)]
        return (sub[1:, 1:] - sub[:-1, 1:] - sub[1:, :-1] + sub[:-1, :-1]) > 0

    std_cache = {}

    def vote(ra, rb, n):
        """Compare prev rows [ra, ra+n) with new rows [rb, rb+n), tile by tile -> (agree, disagree)."""
        nt = n // TILE
        if nt < 1 or tc < 1:
            return 0, 0
        n2 = nt * TILE
        shape = (nt, TILE, tc, TILE)
        wrong = (np.abs(gp[ra:ra + n2, :m2] - gn[rb:rb + n2, :m2]) > 32).reshape(shape).mean(axis=(1, 3))
        if rb not in std_cache:  # texture of the new frame's tiles, computed once per alignment
            rows = (min(h, rb + (h // TILE) * TILE) - rb) // TILE
            std_cache[rb] = gn[rb:rb + rows * TILE, :m2].reshape(rows, TILE, tc, TILE).std(axis=(1, 3))
        informative = std_cache[rb][:nt] > TILE_TEXTURE
        if Ip is not None:
            informative &= ~tiles_hit(Ip, ra, nt)
        if In is not None:
            informative &= ~tiles_hit(In, rb, nt)
        agree = int((informative & (wrong < TILE_WRONG)).sum())
        return agree, int(informative.sum()) - agree

    a0, d0 = vote(0, 0, h)
    masked = Ip is not None or In is not None
    if d0 == 0 and (a0 >= 4 or (a0 + d0 == 0 and not masked)):
        return 0, a0                     # nothing (informative) changed
    if a0 + d0 == 0:
        return None, 0                   # everything left to compare is masked: can't tell
    # moving area: skip rows that are identical in place (sticky header / footer)
    same = (np.abs(gp - gn) > 32).mean(axis=1) < 0.002
    top = int(np.argmin(same))
    bot = h - int(np.argmin(same[::-1]))
    span = bot - top
    if span < TILE * 2:
        return 0, a0

    def rank(a, d):
        # share of informative tiles that DISAGREE - the true position has the lowest share
        # (0 for a static page; only the video's share when a video is playing). Ties -> more agreement.
        return d / (a + d) - 0.0005 * a

    # every plausible shift (and "didn't move") competes on the same terms
    scored = [(rank(a0, d0), a0, d0, 0)]
    max_shift = int(span * 0.68)   # need >= 32% overlap: thin slivers are too easy to mis-match
    cands = _candidates(prev, new, top, bot, mask_prev=ignore_prev, mask_new=ignore_new)
    if hint is not None and hint > 0:   # where the app itself says the page is (precise mode)
        w = max(4, hint // 3)            # the app's position can run ahead of what's drawn (smooth scrolling)
        cands.update(range(max(1, hint - w), hint + w + 1))
    for dy in cands:
        if dy > max_shift or span - dy < TILE * 2:
            continue
        a, d = vote(top + dy, top, span - dy)
        if a + d >= 6:
            scored.append((rank(a, d), a, d, dy))
    scored.sort()
    _, a, d, dy = scored[0]
    rho = d / (a + d)
    runner = next((s for s in scored[1:] if abs(s[3] - dy) > 2), None)
    # how much is there to see on screen in total (known animation excluded)?
    nt_all = span // TILE
    if In is None and Ip is not None:
        # the animation mask belongs to the previous frame: count what's visible there
        g = gp[top:top + nt_all * TILE, :m2].reshape(nt_all, TILE, tc, TILE).std(axis=(1, 3))
        visible = (g > TILE_TEXTURE) & ~tiles_hit(Ip, top, nt_all)
    else:
        if top not in std_cache:
            vote(top, top, span)
        visible = std_cache[top][:nt_all] > TILE_TEXTURE
        if In is not None:
            visible &= ~tiles_hit(In, top, nt_all)
    visible_n = int(visible.sum())
    # accept only if enough tiles line up exactly - and they're a real share of the screen, not a
    # thin sliver that happens to look alike -, what disagrees could be animation, and no other
    # position comes close
    if a < 4 or rho > max_rho:
        return None, a
    if dy != 0 and a < 0.25 * visible_n:
        # small share of the screen: only OK if it's a (near-)flawless match over a substantial overlap
        if not (rho <= 0.08 and a >= 6 and span - dy >= 0.4 * span):
            return None, a
    if runner is not None:
        _, ra, rd, _ = runner
        if rd / (ra + rd) < rho + 0.08:   # another position is about as good: ambiguous
            return None, a
    return dy, a


def static_header(prev, new):
    """Rows at the top that didn't move (sticky headers / toolbars)."""
    h = len(prev)
    hh = 0
    while hh < h // 3 and (np.abs(prev.g[hh] - new.g[hh]) > 32).mean() < 0.04:
        hh += 1
    return hh


def animated_boxes(mask, min_h=24, min_w=24):
    """Bounding boxes (y0, y1, x0, x1 in full-res pixels) of the animated areas in a mask
    (mask is half-res horizontally). Grouped on the tile grid so a video is one box."""
    n, m = mask.shape
    T = TILE
    gh, gw = (n + T - 1) // T, (m + T - 1) // T
    pad = np.zeros((gh * T, gw * T), bool)
    pad[:n, :m] = mask
    grid = pad.reshape(gh, T, gw, T).any(axis=(1, 3))
    seen = np.zeros_like(grid)
    boxes = []
    for i in range(gh):
        for j in range(gw):
            if not grid[i, j] or seen[i, j]:
                continue
            stack, cells = [(i, j)], []
            seen[i, j] = True
            while stack:
                a, b = stack.pop()
                cells.append((a, b))
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    x, y = a + da, b + db
                    if 0 <= x < gh and 0 <= y < gw and grid[x, y] and not seen[x, y]:
                        seen[x, y] = True
                        stack.append((x, y))
            r0, r1 = min(c[0] for c in cells), max(c[0] for c in cells) + 1
            c0, c1 = min(c[1] for c in cells), max(c[1] for c in cells) + 1
            # tighten to the actual animated pixels inside the tile box
            sub = mask[r0 * T:r1 * T, c0 * T:c1 * T]
            rows, cols = np.flatnonzero(sub.any(axis=1)), np.flatnonzero(sub.any(axis=0))
            y0, y1 = r0 * T + rows[0], r0 * T + rows[-1] + 1
            x0, x1 = (c0 * T + cols[0]) * 2, (c0 * T + cols[-1] + 1) * 2
            if y1 - y0 >= min_h and x1 - x0 >= min_w:
                boxes.append((y0, y1, x0, x1))
    return boxes


def static_footer(prev, new, dy):
    """Rows at the bottom that didn't move (sticky footers / toolbars)."""
    h = len(prev)
    fh = 0
    # a row counts as fixed even if a small part changes (a clock, a counter, a blinking icon)
    while fh < h // 3 and (np.abs(prev.g[h - 1 - fh] - new.g[h - 1 - fh]) > 32).mean() < 0.04:
        fh += 1
    return fh if dy > 0 else 0


class _Outline(QWidget):
    """Dashed frame drawn just *outside* the capture area (never appears in the frames)."""

    def __init__(self, logical_rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(logical_rect.adjusted(-4, -4, 4, 4))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.5, Qt.DashLine))
        p.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawRect(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5).adjusted(-0.5, -0.5, 0.5, 0.5))


def animation_mask(a, b):
    """Pixels that changed between two frames taken while the page stood still (videos, GIFs, carets).
    None if nothing changed, or if so much changed that it can't be animation."""
    changed = np.abs(a.g - b.g) > 32
    share = changed.mean()
    if share == 0 or share > 0.85:    # (only called once the page is known to be standing still)
        return None
    return changed


def verify_near(prev, new, guess, ignore_prev=None, ignore_new=None):
    """Frozen mode fallback: we know about how far the page was told to move (`guess` rows). Check the
    positions near it directly, using only what isn't animated. Returns the best dy if it lines up
    cleanly, else None. Used when a big video leaves too little page for the normal search."""
    h = len(prev)
    same = (np.abs(prev.g - new.g) > 32).mean(axis=1) < 0.002
    top = int(np.argmin(same))                       # skip a sticky header
    best = None
    seen_any = False
    w = max(6, int(guess * 0.12))
    for dy in range(max(1, guess - w), guess + w + 1):
        if h - top - dy < TILE * 2:
            continue
        a, b = prev.g[top + dy:h], new.g[top:h - dy]
        ign = np.zeros(a.shape, bool)
        if ignore_prev is not None:
            ign |= ignore_prev[top + dy:h]
        if ignore_new is not None:
            ign |= ignore_new[top:h - dy]
        agree, dis = _vote(a, b, ign)
        seen_any |= agree + dis > 0
        if agree >= 3 and dis <= 0.15 * (agree + dis):
            score = dis / (agree + dis) - 0.001 * agree
            if best is None or score < best[0]:
                best = (score, dy)
    if best:
        return best[1]
    if not seen_any:
        return ("blind", guess)     # nothing but video where the frames overlap: no evidence either way
    return None


class FreezeView(QWidget):
    """A frozen picture of the page, laid exactly over it. Glint's windows are invisible to its own
    captures, so the page underneath is what gets recorded - but your mouse rests on this picture, not
    on the page: hover previews never start and nothing jumps around while you work. Scrolling here
    tells Glint to move the real page a step; the picture then glides to the new position."""

    def __init__(self, session, logical_rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        self.s = session
        self.pm = None
        self.old = None            # picture we're gliding away from
        self.dy = 0                # how far (frame rows) the new picture is below the old one
        self.hh = 0                # sticky header rows: they stay put while the rest glides
        self.t = 1.0
        self.busy = False
        self.setGeometry(logical_rect)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._tick)

    @staticmethod
    def _pm(arr):
        h, w = arr.shape[:2]
        a = np.ascontiguousarray(arr)
        return QPixmap.fromImage(QImage(a.data, w, h, w * 4, QImage.Format_RGB32).copy())

    def set_frame(self, arr):
        self.anim.stop()
        self.pm, self.old, self.t = self._pm(arr), None, 1.0
        self.update()

    def slide_to(self, arr, dy, hh=0):
        """Show the new picture by gliding the old one up by dy rows (dy < 0 glides down)."""
        new = self._pm(arr)
        if self.pm is None or dy == 0 or abs(dy) >= new.height():
            self.set_frame(arr)
            return
        self.anim.stop()
        self.old, self.pm, self.dy, self.hh = self.pm, new, dy, max(0, hh or 0)
        self.t = 0.0
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _tick(self, v):
        self.t = float(v)
        if self.t >= 1.0:
            self.old = None
        self.update()

    def set_busy(self, busy):
        if busy != self.busy:
            self.busy = busy
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        if self.pm is None:
            p.fillRect(self.rect(), QColor(0, 0, 0))
        else:
            k = self.height() / max(1, self.pm.height())          # frame rows -> widget pixels
            W = float(self.width())
            if self.old is not None and self.t < 1.0:
                o = round(self.dy * self.t)                        # rows scrolled so far (whole rows: no seams)
                hh = self.hh
                p.save()
                p.setRenderHint(QPainter.Antialiasing, False)
                p.setClipRect(QRectF(0, hh * k, W, self.height() - hh * k))
                # new picture first, then the old one over it: they overlap exactly, so there's never a gap
                p.drawPixmap(QRectF(0, (self.dy - o) * k, W, self.pm.height() * k), self.pm, QRectF(self.pm.rect()))
                p.drawPixmap(QRectF(0, -o * k, W, self.old.height() * k), self.old, QRectF(self.old.rect()))
                p.restore()
                if hh:
                    p.drawPixmap(QRectF(0, 0, W, hh * k), self.pm, QRectF(0, 0, self.pm.width(), hh))
            else:
                p.drawPixmap(QRectF(self.rect()), self.pm, QRectF(self.pm.rect()))
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont("Segoe UI")
        f.setPixelSize(13)
        p.setFont(f)
        if self.busy:
            text = "Moving the page…"
        else:
            text = "Scroll here to capture more     Enter  Done     Esc  Cancel"
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 32, 32
        box = QRectF((self.width() - w) / 2, self.height() - h - 16, w, h)
        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        p.setBrush(QColor(20, 20, 20, 230))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor("#ececec"))
        p.drawText(box, Qt.AlignCenter, text)

    # the control bar and the preview must never end up hidden behind this picture
    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.s._raise_controls()

    def mousePressEvent(self, e):
        self.s._raise_controls()
        super().mousePressEvent(e)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d < 0:
            self.s.request_step()
        elif d > 0:
            self.s.request_back()
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Space, Qt.Key_PageDown, Qt.Key_Down):
            self.s.request_step()
        elif k in (Qt.Key_PageUp, Qt.Key_Up, Qt.Key_Backspace):
            self.s.request_back()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.s.stop()
        elif k == Qt.Key_Escape:
            self.s.cancel()
        else:
            super().keyPressEvent(e)


class _Bar(QWidget):
    """Floating control bar: status, Frozen | Manual switch, Auto, Done, cancel."""

    def __init__(self, session, logical_rect, allow_auto):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout
        from . import theme
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #ff5a52; background: transparent; font-size: 9pt;")
        self.label = QLabel("Ready")
        self.label.setStyleSheet("color: #ececec; background: transparent;")
        self.label.setMinimumWidth(110)
        row.addWidget(self.dot)
        row.addWidget(self.label)
        row.addSpacing(6)
        self.group = QButtonGroup(self)
        self.manual = QToolButton()
        self.manual.setText("Manual")
        self.manual.setToolTip("You scroll - on the frozen picture - at your own pace.\n"
                               "Glint moves the page underneath and stitches. Videos and hover previews can't throw it off.")
        self.auto = QToolButton()
        self.auto.setText("Auto")
        self.auto.setToolTip("Glint scrolls to the bottom by itself. Click Manual to stop it.")
        for b in (self.manual, self.auto):
            b.setObjectName("chip")
            b.setCheckable(True)
            self.group.addButton(b)
            row.addWidget(b)
        self.manual.setEnabled(allow_auto)
        self.auto.setEnabled(allow_auto)
        if not allow_auto:
            tip = "Games: scroll the game yourself (Glint never scrolls a game's window for you)"
            self.manual.setToolTip(tip)
            self.auto.setToolTip(tip)
        self.manual.clicked.connect(lambda: session.choose("manual"))
        self.auto.clicked.connect(lambda: session.choose("auto"))
        row.addSpacing(6)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(session.stop)
        cancel = QToolButton()
        cancel.setIcon(theme.icon("close", 16))
        cancel.setToolTip("Cancel")
        cancel.clicked.connect(session.cancel)
        row.addWidget(done)
        row.addWidget(cancel)
        outer.addLayout(row)
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #9a9a9a; background: transparent; font-size: 8.5pt;")
        outer.addWidget(self.hint)
        self.adjustSize()
        self.setFixedWidth(max(self.width(), 440))
        scr = QGuiApplication.screenAt(logical_rect.center()) or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry()
        x = logical_rect.center().x() - self.width() // 2
        y = logical_rect.bottom() + 12
        if y + self.height() > avail.bottom():
            y = logical_rect.top() - self.height() - 12
        if y < avail.top():  # region fills the screen: sit in the corner
            y = avail.bottom() - self.height() - 12
            x = avail.right() - self.width() - 12
        self.move(max(avail.left() + 8, min(x, avail.right() - self.width() - 8)), y)

    def set_mode(self, mode, auto=False):
        if mode == "freeze":
            (self.auto if auto else self.manual).setChecked(True)
        else:                                  # live fallback: neither choice is active
            self.group.setExclusive(False)
            self.manual.setChecked(False)
            self.auto.setChecked(False)
            self.group.setExclusive(True)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.setBrush(QColor(22, 22, 22, 245))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)


class _Preview(QWidget):
    """Live view of the stitched image as it grows, with a status colour:
    green = confident, yellow = unsure (check that join), red = lost track."""
    COLORS = {"good": QColor("#3ecf6b"), "unsure": QColor("#f2c94c"), "lost": QColor("#ff5a52")}
    W = 132

    def __init__(self, logical_rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pm = None
        self.state = "good"
        scr = QGuiApplication.screenAt(logical_rect.center()) or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry()
        hgt = min(420, max(200, logical_rect.height()))
        x = logical_rect.right() + 14
        if x + self.W > avail.right():
            x = logical_rect.left() - 14 - self.W
        if x < avail.left():                       # no room either side: sit inside, top-right
            x = logical_rect.right() - self.W - 10
        y = max(avail.top() + 8, min(logical_rect.top(), avail.bottom() - hgt - 8))
        self.setGeometry(x, y, self.W, hgt)

    def set_image(self, img):
        self.pm = QPixmap.fromImage(img)
        self.update()

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(22, 22, 22, 240))
        p.drawRoundedRect(r, 10, 10)
        if self.pm is not None and not self.pm.isNull():
            inner = r.adjusted(6, 6, -6, -6)
            pm = self.pm.scaledToWidth(int(inner.width()), Qt.SmoothTransformation)
            src_h = min(pm.height(), int(inner.height()))
            # always show the newest (bottom) part
            p.drawPixmap(QRectF(inner.x(), inner.bottom() - src_h, inner.width(), src_h), pm,
                         QRectF(0, pm.height() - src_h, pm.width(), src_h))
        p.setPen(QPen(self.COLORS[self.state], 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)


HINTS = {
    "freeze": "Scroll on the picture (or Space / ↓) to capture more. ↑ undoes a step.",
    "freeze_auto": "Scrolling to the bottom by itself. Click Manual to stop it there.",
    "seam": "Couldn't line that step up, so it was undone. Scroll again (smaller steps), or press Done.",
    "noscroll": "Glint can't move this app's page, so it's watching instead: scroll the page yourself.",
    "undone": "Step undone.",
    "manual": "Live mode: scroll the page yourself, then press Done. (Used for games and apps Glint can't scroll.)",
    "auto": "Glint is scrolling and stops at the bottom.  Switch to Manual to take over.",
    "above": "You are above where you were. Scroll back down to keep going.",
    "lost": "Lost track (scrolled too fast?). Scroll back up a little.",
    "end": "Reached the end. Press Done, or switch to Manual to add more.",
    "stuck": "Could not follow the page here, switched to Manual. Scroll yourself.",
    "max": "Reached the maximum height.",
}


class ScrollCapture(QObject):
    """Two ways to scroll, switchable at any time:

    manual - YOU scroll (wheel, scrollbar, keys) at your own pace; Glint watches and stitches.
             Sends no input at all, so it is also allowed in games.
    auto   - Glint scrolls with the mouse wheel and stops at the end of the page.

    Stitching is always relative to the "frontier" frame (the one whose bottom is the bottom of the
    stitched image), so scrolling back up never duplicates content.
    """
    finished = Signal(QImage, dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, rect, info, mode="manual", allow_auto=True):
        super().__init__()
        self.rect = QRect(rect)
        self.info = info
        self.allow_auto = allow_auto
        self.mode = mode if allow_auto else "manual"
        self.notches = 2
        self.no_move = 0
        self.retries = 0
        self.stopped = False
        self.result = []
        self.total = 0
        self.fh = None
        self.footer = None
        self.frontier = None   # (array, features) of the frame at the bottom of the result
        self._cursor_back = winapi.cursor_pos()
        self._done = False
        lr = phys_to_logical(self.rect)
        self.outline = _Outline(lr)
        self.bar = _Bar(self, lr, allow_auto)
        self.bar.set_mode(self.mode)
        self.preview = _Preview(lr)
        self._preview_at = 0.0
        self.manual_timer = QTimer(self)
        self.manual_timer.setInterval(90)
        self.manual_timer.timeout.connect(self._manual_tick)
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_poll)
        self._settle = []
        # frozen mode
        self.view = None
        self.kf = None               # current keyframe: (frame, features, at-rest animation mask)
        self.undo = []               # one entry per step, to undo it
        self.auto_steps = False
        self._gen = None             # running step (generator), driven by step_timer
        self._queued = 0             # steps asked for while one was running
        self.step_timer = QTimer(self)
        self.step_timer.setSingleShot(True)
        self.step_timer.timeout.connect(self._tick)
        self.wheel_px = None         # learned: pixels per wheel notch (message scrolling)
        self.scroll_fail = 0
        c = self.rect.center()
        hw = user32.WindowFromPoint(ctypes.c_int64((c.y() << 32) | (c.x() & 0xFFFFFFFF)).value)
        self.target = hw             # the window under the area - asked to scroll, never sent input

    # ---- helpers
    def _grab(self):
        full, vx, vy = grabber.grab()
        return to_array(full.copy(self.rect.translated(-vx, -vy)))

    def _wheel(self, notches):
        c = self.rect.center()
        user32.SetCursorPos(c.x(), c.y())
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_uint32(-120 * notches & 0xFFFFFFFF).value, 0)

    def _status(self, hint=None):
        precise = " · precise" if getattr(self, "src", None) is not None else ""
        self.bar.label.setText(f"{self.total:,} px{precise}")
        key = hint or (("freeze_auto" if self.auto_steps else "freeze") if self.mode == "freeze" else self.mode)
        self.bar.hint.setText(HINTS[key])
        self._update_preview()

    def _update_preview(self, force=False):
        """Refresh the live preview (throttled) and its colour."""
        import time as _t
        if not self.result:
            return
        state = "lost" if getattr(self, "lost", False) else ("unsure" if getattr(self, "uncertain", False) else "good")
        self.preview.set_state(state)
        now = _t.monotonic()
        if not force and now - self._preview_at < 0.15:
            return
        self._preview_at = now
        w = self.result[0].shape[1]
        need = int(self.preview.height() * w / (self.preview.W - 12)) + 1
        parts, n = [], 0
        for part in reversed(self.result):
            parts.append(part)
            n += len(part)
            if n >= need:
                break
        arr = np.ascontiguousarray(np.vstack(parts[::-1])[-need:])
        hh, ww = arr.shape[:2]
        img = QImage(arr.data, ww, hh, ww * 4, QImage.Format_RGB32).scaledToWidth(
            self.preview.W - 12, Qt.SmoothTransformation)
        self.preview.set_image(img)

    # ---- flow
    def start(self):
        self.outline.show()
        self.bar.show()
        # our own bar/outline must never end up in the stitched image
        self.preview.show()
        winapi.exclude_from_capture(self.outline.winId())
        winapi.exclude_from_capture(self.bar.winId())
        winapi.exclude_from_capture(self.preview.winId())
        # No global Enter/Esc: the app you're scrolling needs its keys. Done = button or capture hotkey.
        QTimer.singleShot(120, self._first)

    def _first(self):
        frame = self._grab()
        f = features(frame)
        self.result = [frame]
        self.total = len(frame)
        self.frontier = (frame, f)   # frame whose bottom is the bottom of the stitched image
        self.last = (frame, f)       # most recent frame we know the position of
        self.pos = 0                 # page position of `last`  (rows, relative to the first frame)
        self.front_pos = 0           # page position of `frontier`
        self.anim = None             # pixels known to animate (video/GIF), in `poll` coordinates
        self.hh = None               # sticky header height
        self.stills = {}             # one clean frame per video: key -> (result_y, x, pixels)
        self.poll = None             # the most recent check
        self.lost = False
        self.uncertain = False
        # precise mode: the app's own scroll position (UI Automation), when it reports one
        self.src = None
        self.k = None                # pixels per percent, learned from verified movements
        if self.allow_auto:          # never for games
            from .uia import ScrollSource
            c = self.rect.center()
            self.src = ScrollSource.at(c.x(), c.y())
        self.pct_last = self.pct_front = self.src.percent() if self.src is not None else None
        self._pct_now = self.pct_last
        self.uia_frac = 0.5          # auto: scroll this share of a screen per step
        self.set_mode(self.mode)

    def set_mode(self, mode):
        if mode == "auto":
            mode = "freeze"          # "auto" from older settings = frozen stepping
        if mode == "freeze" and not self.allow_auto:
            mode = "manual"
        self.mode = mode
        self.bar.set_mode(mode, self.auto_steps)
        self.manual_timer.stop()
        self.auto_timer.stop()
        if mode != "freeze":
            self.auto_steps = False
            self.bar.set_mode(self.mode, False)
            if self.view is not None:
                self.view.hide()
        if self.frontier is None or self.stopped:
            return
        self._status()
        if mode == "freeze":
            self._enter_freeze()
            return
        if mode == "manual":
            self.manual_timer.start()
        else:
            self.no_move = 0
            self._warm = 3          # look for a moment first, to learn any video/animation on the page
            self._settle = 0
            self._moved = 0
            self.auto_timer.start(90)

    @staticmethod
    def _shift(a, b, max_rho=STRICT, mask_a=None, mask_b=None, allow_up=True, hint=None):
        """Signed scroll from frame a to frame b: +down, -up, 0 = didn't move, None = can't tell.
        mask_a / mask_b mark known animation in a's / b's coordinates. `hint` = predicted signed
        movement from the app's own scroll position (precise mode), if known."""
        if hint is not None and hint < -30:     # the app clearly says it went up: only look up
            back, _ = find_shift(b, a, max_rho, ignore_prev=mask_b, ignore_new=mask_a, hint=-hint)
            return -back if back is not None else None
        dy, _ = find_shift(a, b, max_rho, ignore_prev=mask_a, ignore_new=mask_b,
                           hint=hint if hint is not None and hint > 2 else None)
        strong_down = hint is not None and hint > 30
        if dy is not None:
            return dy
        if not allow_up or strong_down:
            return None
        back, _ = find_shift(b, a, max_rho, ignore_prev=mask_b, ignore_new=mask_a)
        return -back if back is not None else None

    # The animation mask (`self.anim`) always belongs to the most recent check (`self.poll`).
    def _still(self, P, f):
        """Did the page stay put between two checks? "Didn't move" has to clearly beat every possible
        scroll position (a playing video can make a still page look busy; a page scrolled by exactly
        one repeated row can look still - the full ranking handles both)."""
        dy, _ = find_shift(P, f, max_rho=0.85, ignore_prev=self.anim)
        self._hint = dy          # lenient guess, used as direction evidence
        if dy != 0:
            return False
        # the search above only sees downward scrolls - make sure it didn't scroll UP either
        up, _ = find_shift(f, P, max_rho=0.85, ignore_new=self.anim)
        if up:
            self._hint = -up
            return False
        # "didn't move" must be backed by positive evidence, not just win by default
        return looks_still(P, f, self.anim)

    def _learn_animation(self, P, f):
        """Page didn't scroll but pixels changed -> animation (video, GIF...). Remember where."""
        changed = np.abs(P.g - f.g) > 32
        if changed.mean() > 0.5:   # implausible - probably the page itself changed; don't learn
            return
        if self.anim is not None and (self.anim | changed).mean() > 0.6:
            self.anim = None       # mask grew implausibly big - start over rather than hide the page
            return
        self.anim = changed if self.anim is None else (self.anim | changed)
        if self.anim.mean() > 0.7:
            self.anim = None

    def _move_animation(self, dy):
        """Content moved up by dy rows: move the mask with it."""
        if self.anim is None or dy == 0:
            return
        m = np.zeros_like(self.anim)
        if 0 < dy < len(m):
            m[:-dy] = self.anim[dy:]
        elif 0 < -dy < len(m):
            m[-dy:] = self.anim[:dy]
        self.anim = m if m.any() else None

    def _observe(self, frame, f):
        """Process one new check. Returns 'still', 'moved', 'lost' or 'resynced'."""
        P = self.poll if self.poll is not None else self.last[1]
        self.poll = f
        self._hint = None
        self._pct_now = self.src.percent() if self.src is not None else None
        if fdiff(f, P) < 0.3 or self._still(P, f):
            self._learn_animation(P, f)
            if self.lost:
                return "resynced" if self._resync(frame, f) else "lost"
            self.last = (frame, f)
            self.pct_last = self._pct_now if self._pct_now is not None else self.pct_last
            return "still"
        if self.lost:
            self.anim = None
            return "resynced" if self._resync(frame, f) else "lost"
        # if the lenient check already saw a downward scroll, don't go hunting for an upward one
        hint = getattr(self, "_hint", None)
        pred = self._predict(self.pct_last)
        dy = self._shift(self.last[1], f, mask_a=self.anim, allow_up=not (hint and hint > 0), hint=pred)
        if dy is None:
            self.lost = True
            self.anim = None
            return "lost"
        self._move_animation(dy)
        self._advance(frame, f, dy)
        self.pct_last = self._pct_now
        return "moved"

    def _resync(self, frame, f):
        """Find our place again by matching against the last stitched frame (strictly)."""
        back = self._shift(self.frontier[1], f, max_rho=RESYNC, mask_b=self.anim,
                           hint=self._predict(self.pct_front))
        if back is None:
            return False
        self.lost = False
        self.uncertain = True       # show yellow briefly: we had lost track
        self._advance(frame, f, self.front_pos + back - self.pos)
        self.pct_last = self._pct_now
        return True

    # ---- precise mode helpers (app reports its scroll position)
    def _predict(self, pct_from):
        """Expected movement in pixels since a known scroll position, or None."""
        if self.k is None or pct_from is None or self._pct_now is None:
            return None
        return int(round((self._pct_now - pct_from) * self.k))

    def _settled_check(self, state):
        """When the app's reported position has stopped changing (smooth scrolling finished), compare
        it with where the image says we are: learn the scale, and flag disagreements (yellow)."""
        p = self._pct_now
        prev = getattr(self, "_pct_prev_poll", None)
        self._pct_prev_poll = p
        if p is None or prev is None or abs(p - prev) > 1e-6 or self.lost or state == "lost":
            return
        anchor = getattr(self, "_anchor", None)
        self._anchor = (p, self.pos)
        if anchor is None:
            return
        dp, dpos = p - anchor[0], self.pos - anchor[1]
        if abs(dp) < 0.3:
            if abs(dpos) > 40:       # app says it barely moved, image says it moved a lot
                self.uncertain = True
            return
        k = dpos / dp
        if k <= 0:
            self.uncertain = True    # app and image disagree on direction
            return
        if self.k is not None:
            expected = dp * self.k
            self.uncertain = abs(expected - dpos) > max(30, 0.12 * abs(dpos))
        else:
            self.uncertain = False
        self.k = k if self.k is None else 0.6 * self.k + 0.4 * k

    def _advance(self, frame, f, dy):
        self.pos += dy
        self.last = (frame, f)
        gain = self.pos - self.front_pos
        if gain > 0:
            self._append(frame, f, gain)
            self.front_pos = self.pos
            self.pct_front = getattr(self, "_pct_now", None)

    def _append(self, frame, f, dy):
        """Add the dy new rows at the bottom of `frame` (it sits dy rows below the frontier)."""
        h = len(f)
        if self.fh is None:  # sticky footer height: measured once, kept fixed so seams line up
            self.fh = static_footer(self.frontier[1], f, dy)
            self.hh = static_header(self.frontier[1], f)
            if self.fh and len(self.result) == 1:
                self.result[0] = self.result[0][:h - self.fh]
                self.total -= self.fh
        fh = self.fh
        rows = frame[max(0, h - dy - fh): h - fh]
        if len(rows):
            self.result.append(rows)
            self.total += len(rows)
        self.footer = frame[h - fh:] if fh else None
        self.frontier = (frame, f)
        if self.total >= MAX_HEIGHT:
            self._status("max")
            self.stop()

    # ---- frozen: Glint moves the page in clean steps while you look at a still picture
    def _enter_freeze(self):
        if self.view is None:
            self.view = FreezeView(self, phys_to_logical(self.rect))
            winapi.exclude_from_capture(self.view.winId())
        frame, f = self.last
        self.view.set_frame(frame)
        self.view.show()
        self.view.activateWindow()
        self.view.setFocus()
        self._raise_controls()
        QTimer.singleShot(50, self._raise_controls)     # again, once Windows has finished activating it
        if self.kf is None or self.pos != self.front_pos:
            self._run(self._rekey_gen())

    def _raise_controls(self):
        for w in (self.preview, self.bar):
            if w is not None and w.isVisible():
                w.raise_()

    def choose(self, which):
        """The bar's Manual / Auto buttons (both use the frozen picture)."""
        if self.mode != "freeze":
            self.set_mode("freeze")
        self.set_auto(which == "auto")

    def set_auto(self, on):
        self.auto_steps = bool(on) and self.mode == "freeze"
        self.bar.set_mode(self.mode, self.auto_steps)
        self._status()
        if self.auto_steps and self._gen is None:
            self.request_step()

    def request_step(self):
        if self.mode != "freeze" or self.stopped:
            return
        if self._gen is not None:
            self._queued = min(2, self._queued + 1)
            return
        self._run(self._step_gen(STEP))

    def request_back(self):
        if self.mode != "freeze" or self.stopped or self._gen is not None:
            return
        if not self.undo:
            return
        self._run(self._undo_gen())

    def _run(self, gen):
        self._gen = gen
        if self.view is not None:
            self.view.set_busy(True)
        self._tick()

    def _tick(self):
        if self._gen is None or self.stopped:
            return
        try:
            ms = next(self._gen)
        except StopIteration:
            self._gen = None
            if self.view is not None:
                self.view.set_busy(False)
            if self._queued and not self.stopped and self.mode == "freeze":
                self._queued -= 1
                self._run(self._step_gen(STEP))
            elif self.auto_steps and not self.stopped and self.mode == "freeze":
                QTimer.singleShot(0, self._auto_next)
            return
        self.step_timer.start(ms)

    def _auto_next(self):
        if self.auto_steps and self._gen is None and not self.stopped and self.mode == "freeze":
            self._run(self._step_gen(STEP))

    def _settle_gen(self, out):
        """Wait until the page stops moving (smooth scrolling done), then learn what still changes on
        its own (videos). Fills out = [frame, features, animation mask].
        Fast path: two identical looks in a row = settled and nothing on the page animates."""
        last = None
        stills = 0
        animated = False
        for _ in range(90):                       # give up waiting after ~3.5 s
            fr = self._grab()
            f = features(fr)
            if last is not None:
                d = fdiff(f, last[1])
                if d < 0.02:                      # identical: settled, and nothing is playing
                    out[:] = [fr, f, None]
                    return
                if looks_still(last[1], f) and find_shift(last[1], f, max_rho=0.85)[0] == 0:
                    animated = True               # standing still, but something on it plays
                    stills += 1
                    if stills >= 2:
                        break
                else:
                    stills = 0                    # (a 1-2 px creep at the end of smooth scrolling isn't "still")
            last = (fr, f)
            yield 35
        if not animated or last is None:
            out[:] = [last[0], last[1], None] if last is not None else [fr, f, None]
            return
        yield 70                                  # one more look to see exactly what plays
        fr = self._grab()
        f = features(fr)
        mask = animation_mask(last[1], f) if find_shift(last[1], f, max_rho=0.85)[0] == 0 else None
        out[:] = [fr, f, mask]

    def _rekey_gen(self):
        """(Re)take the keyframe where the page is now - e.g. after switching from Manual."""
        out = []
        yield from self._settle_gen(out)
        fr, f, mask = out
        if self.kf is not None and self.pos != self.front_pos:
            dy, _ = find_shift(self.frontier[1], f, max_rho=0.5, ignore_new=mask)
            if dy is None:
                self._status("above")
                return
            self.pos = self.front_pos + dy
            self._advance(fr, f, dy)
        self.kf = (fr, f, mask)
        self.anim = mask
        self.view.set_frame(fr)
        self._status()

    def _scroll_page(self, frac):
        """Ask the app to scroll by frac of the view (+ down). No input is simulated and the mouse
        never moves: the app's own scroll control (UI Automation) if it has one, else a scroll message
        posted to its window. Returns how ("uia" / "msg") or None."""
        h = self.rect.height()
        if self.src is not None:
            p, vs = self.src.percent(), self.src.view_size()
            if p is not None and vs is not None and 0 < vs < 100:
                step = frac * vs / (100.0 - vs) * 100.0
                if self.src.set_percent(max(0.0, min(100.0, p + step))):
                    return "uia"
        if self.target:
            px = self.wheel_px or 100.0 * max(1.0, h / max(1, phys_to_logical(self.rect).height()))
            notches = max(1, int(abs(frac) * h / px))      # round DOWN: never overshoot the overlap
            delta = (-120 if frac > 0 else 120) * notches
            c = self.rect.center()
            lparam = ((c.y() & 0xFFFF) << 16) | (c.x() & 0xFFFF)
            wparam = (delta & 0xFFFF) << 16
            self._notches = notches
            for hw in (self.target, user32.GetAncestor(self.target, 2)):   # 2 = GA_ROOT
                if hw:
                    user32.PostMessageW(hw, WM_MOUSEWHEEL, wparam, lparam)
                    break
            return "msg"
        return None

    def _step_gen(self, frac, depth=0):
        prev = self.kf
        if prev is None:
            return
        self._pct_before = self.src.percent() if self.src is not None else None
        how = self._scroll_page(frac)
        if how is None:
            self._no_scroll()
            return
        yield 40
        out = []
        yield from self._settle_gen(out)
        fr, f, mask = out
        guessed = False
        dy, _ = find_shift(prev[1], f, max_rho=0.5, ignore_prev=prev[2], ignore_new=mask)
        if dy == 0 and depth < 2:
            # make sure: look again once things have certainly settled
            yield 250
            out = []
            yield from self._settle_gen(out)
            fr, f, mask = out
            dy, _ = find_shift(prev[1], f, max_rho=0.5, ignore_prev=prev[2], ignore_new=mask)
        if dy == 0 and getattr(self, "px_per_frac", None):
            # "didn't move" can be an illusion when a big video hides almost everything except a sticky
            # header (which never moves): check the distance we asked for before believing it
            moved = self._verify(prev, f, mask, frac)
            if moved:
                dy, guessed = moved, True
        if dy == 0:
            # nothing moved: the end of the page - or this app ignores our scroll requests
            if how == "msg" and self.total <= len(prev[1]) and self.target and depth == 0:
                root = user32.GetAncestor(self.target, 2)
                if root and root != self.target:      # some apps only listen on their main window
                    self.target = root
                    yield from self._step_gen(frac, depth + 1)
                    return
            if self.total <= len(prev[1]):
                self._no_scroll()
                return
            self.auto_steps = False
            self.bar.set_mode(self.mode, False)
            self._status("end")
            self.bar.dot.setStyleSheet("color: #5ad17a; background: transparent; font-size: 9pt;")
            return
        if dy is None and getattr(self, "px_per_frac", None):
            # a big video can leave too little page for the normal search - check where the page
            # should be (we know how far we asked it to move), using only the parts that aren't video
            dy = self._verify(prev, f, mask, frac)
            guessed = dy is not None
        if dy is None:
            # couldn't line it up: put the page back where it was, and next time take smaller steps
            self._scroll_page(-frac)
            yield 120
            yield from self._settle_gen([])
            self.uncertain = True
            if depth == 0 and frac > 0.2:
                yield from self._step_gen(frac / 2, depth + 1)
                return
            self.auto_steps = False
            self.bar.set_mode(self.mode, False)
            self._status("seam")
            return
        if dy > 0 and not guessed:
            self._clean_steps = getattr(self, "_clean_steps", 0) + 1
            # learn how far a step really moves (the largest seen: the last step can be cut short by
            # the end of the page)
            if how == "msg" and getattr(self, "_notches", 0):
                self.wheel_px = max(self.wheel_px or 0, dy / self._notches)
            ppf = dy / frac
            self.px_per_frac = max(getattr(self, "px_per_frac", 0) or 0, ppf) if how == "msg" else \
                (ppf if not getattr(self, "px_per_frac", None) else 0.7 * self.px_per_frac + 0.3 * ppf)
        self.undo.append((self.pos, self.front_pos, len(self.result), self.total, self.frontier, self.footer,
                          dict(self.stills), prev, frac))
        self.uncertain = guessed          # yellow: lined up from the expected distance - worth a glance
        if not guessed:
            self._blind = 0
        self._advance(fr, f, dy)
        self.kf = (fr, f, mask)
        self.anim = mask
        self._keep_video_stills(fr, "moved")
        self.view.slide_to(fr, dy, self.hh or 0)
        self._raise_controls()
        self._status()

    def _verify(self, prev, f, mask, frac):
        r = verify_near(prev[1], f, int(round(frac * self.px_per_frac)), prev[2], mask)
        if isinstance(r, tuple):
            # only video where the frames overlap: trust the distance we asked for - but never twice
            # in a row more than twice (if the page has really stopped, we'd be inventing content)
            self._blind = getattr(self, "_blind", 0) + 1
            if self.src is not None and self._pct_before is not None:
                now = self.src.percent()
                if now is not None and abs(now - self._pct_before) < 1e-6:
                    return None          # the app says it didn't move: that's the end, not a blind step
            return r[1] if self._blind <= 2 and getattr(self, "_clean_steps", 0) >= 2 else None
        return r

    def _undo_gen(self):
        pos, front_pos, n, total, frontier, footer, stills, kf, frac = self.undo.pop()
        was = self.pos
        self.pos, self.front_pos, self.total = pos, front_pos, total
        del self.result[n:]
        self.frontier, self.footer, self.stills = frontier, footer, stills
        self.kf = kf
        self.last = (kf[0], kf[1])
        self.anim = kf[2]
        self.view.slide_to(kf[0], pos - was, self.hh or 0)      # glide back down
        self._scroll_page(-frac)       # the next step is matched against kf, so landing near is enough
        yield 120
        yield from self._settle_gen([])
        self._status("undone")

    def _no_scroll(self):
        self.auto_steps = False
        self.bar.set_mode(self.mode, False)
        self.set_mode("manual")
        self._status("noscroll")

    # ---- manual: watch the user scroll
    def _keep_video_stills(self, frame, state):
        """A playing video gets stitched from many different moments (looks torn). Keep one complete,
        clean frame of each video instead, and lay it over the stitched result at the end."""
        if state == "lost" or self.anim is None or self.lost:
            return
        h = len(frame)
        lo, hi = (self.hh or 0), h - (self.fh or 0)
        w = frame.shape[1]
        for y0, y1, x0, x1 in animated_boxes(self.anim):
            # pad a little: the learned area can miss edge pixels that happened not to change, and the
            # page around a video is identical in every frame anyway
            y0, y1, x0, x1 = y0 - 12, y1 + 12, max(0, x0 - 12), min(w, x1 + 12)
            if y0 <= lo + 1 or y1 >= hi - 1:     # cut off by the edge of the view: not complete yet
                continue
            ry = self.pos + y0                    # where this lands in the stitched image
            # one entry per video (same top-left on the page); keep the biggest complete view of it -
            # the learned area grows as more of the video scrolls into view
            key = (round(ry / 24), round(x0 / 24))
            old = self.stills.get(key)
            if old is None or (y1 - y0) * (x1 - x0) > old[2].shape[0] * old[2].shape[1]:
                self.stills[key] = (ry, x0, frame[y0:y1, x0:x1].copy())

    def _manual_tick(self):
        frame = self._grab()
        state = self._observe(frame, features(frame))
        self._settled_check(state)
        self._keep_video_stills(frame, state)
        # check quickly while the page is moving (smaller steps are easier to follow), relax when still
        self.manual_timer.setInterval(40 if state in ("moved", "resynced") else 90)
        if state == "lost":
            self._status("lost")
        elif self.pos < self.front_pos:
            self._status("above")
        else:
            self._status()

    # ---- auto: scroll for the user
    def _auto_scroll(self):
        if self.stopped or self.mode != "auto":
            return
        self._step_back = None
        p = self.src.percent() if self.src is not None else None
        vs = self.src.view_size() if p is not None else None
        if p is not None and vs is not None and vs < 100:
            # precise: set the app's scroll position directly - no simulated mouse input, pointer stays put
            step = self.uia_frac * vs / (100.0 - vs) * 100.0
            if self.src.set_percent(p + step):
                self._step_back = p
        if self._step_back is None:
            self.used_wheel = True
            self._wheel(self.notches)
        self._settle = 0
        self._moved = 0
        self.auto_timer.start(140)

    def _auto_poll(self):
        """Keep checking until the page settles (smooth scrolling done), then take the next step."""
        if self.mode != "auto" or self.stopped:
            return
        before = self.pos
        frame = self._grab()
        state = self._observe(frame, features(frame))
        self._settled_check(state)
        self._keep_video_stills(frame, state)
        if getattr(self, "_warm", 0) > 0:
            self._warm -= 1
            if self._warm == 0:
                return self._auto_scroll()
            self.auto_timer.start(90)
            return
        self._moved += self.pos - before
        self._settle += 1
        if state == "lost":
            if self.retries < 4:  # overshot / new video came into view: step back, look, then smaller steps
                self.retries += 1
                if self._step_back is not None:      # precise: jump straight back, then smaller steps
                    self.src.set_percent(self._step_back)
                    self.uia_frac = max(0.15, self.uia_frac / 2)
                else:
                    self._wheel(-self.notches)
                    self.notches = max(1, self.notches // 2)
                self._warm = 4          # pause to learn any video and re-find our place
                self._settle = 0
                self._moved = 0
                self.auto_timer.start(350)
                return
            self.set_mode("manual")
            self._status("stuck")
            return
        if state == "still" and self._settle >= 2 or self._settle >= 12:
            return self._auto_step()
        self.auto_timer.start(90)

    def _auto_step(self):
        h = len(self.last[1])
        if self._moved == 0:  # nothing moved (a video may still be playing): end of the page
            self.no_move += 1
            if self.no_move >= 2:
                self._status("end")
                self.bar.dot.setStyleSheet("color: #5ad17a; background: transparent; font-size: 9pt;")
                return  # wait for the user - they decide when it is finished
            return self._auto_scroll()
        self.no_move = 0
        self.retries = 0
        self.uia_frac = min(0.5, self.uia_frac * 1.25)   # recover step size after a cautious stretch
        per_notch = abs(self._moved) / self.notches
        if per_notch > 0:
            self.notches = int(max(1, min(15, (h - (self.fh or 0)) * 0.5 // per_notch)))
        self._status()
        self._auto_scroll()

    # ---- end
    def stop(self):
        self.stopped = True
        self._finish(keep=True)

    def cancel(self):
        self.stopped = True
        self._finish(keep=False)

    def _finish(self, keep):
        if self._done:
            return
        self._done = True
        self.manual_timer.stop()
        self.auto_timer.stop()
        self.step_timer.stop()
        self._gen = None
        if self.view is not None:
            self.view.close()
        self.outline.close()
        self.bar.close()
        self.preview.close()
        if getattr(self, "used_wheel", False):
            user32.SetCursorPos(*self._cursor_back)
        if not keep:
            self.cancelled.emit()
            return
        if not self.result:
            self.failed.emit("Nothing captured")
            return
        parts = list(self.result)
        if self.footer is not None and len(self.footer):
            parts.append(self.footer)
        arr = np.ascontiguousarray(np.vstack(parts)[:MAX_HEIGHT])
        h, w = arr.shape[:2]
        for ry, x0, patch in self.stills.values():
            ph, pw = patch.shape[:2]
            if 0 <= ry and ry + ph <= h - (self.fh or 0) and x0 + pw <= w:
                arr[ry:ry + ph, x0:x0 + pw] = patch
        img = QImage(arr.data, w, h, w * 4, QImage.Format_RGB32).copy()
        self.finished.emit(img, self.info)
