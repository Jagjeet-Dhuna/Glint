"""Screen grabbing.

Primary path: DXGI Desktop Duplication (via dxcam). It reads the final composed frame from the
GPU, so it captures DirectX/Vulkan games in borderless *and* fullscreen mode, where GDI BitBlt
often returns black. Falls back to BitBlt per monitor if duplication is unavailable.
"""
import threading

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter

from . import winapi


class Grabber:
    def __init__(self):
        self._cams = None      # device name -> (camera, QRect desktop coords)
        self._last = {}        # device name -> last QImage (duplication returns None if nothing changed)
        self._lock = threading.Lock()
        self.dxgi_ok = True

    def warm_up(self):
        try:
            self._ensure()
        except Exception:
            self.dxgi_ok = False

    def _ensure(self):
        if self._cams is not None:
            return
        import dxcam
        factory = getattr(dxcam, "__factory")
        cams = {}
        for d, outputs in enumerate(factory.outputs):
            for o in range(len(outputs)):
                cam = dxcam.create(device_idx=d, output_idx=o, output_color="BGRA")
                desc = cam._output.desc
                c = desc.DesktopCoordinates
                cams[desc.DeviceName] = (cam, QRect(c.left, c.top, c.right - c.left, c.bottom - c.top))
        self._cams = cams

    def _reset(self):
        try:
            for cam, _ in (self._cams or {}).values():
                cam.release()
        except Exception:
            pass
        self._cams = None
        self._last = {}

    def _grab_dxgi(self, name):
        cam, rect = self._cams[name]
        frame = cam.grab()
        if frame is None:
            return self._last.get(name)
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, w * 4, QImage.Format_RGB32).copy()
        self._last[name] = img
        return img

    def grab(self):
        """Capture every monitor. Returns (QImage of whole virtual desktop, vx, vy)."""
        with self._lock:
            vx, vy, vw, vh = winapi.virtual_screen()
            mons = winapi.monitors()
            frames = {}
            if self.dxgi_ok:
                for attempt in (0, 1):
                    try:
                        self._ensure()
                        for name, _ in mons:
                            if name in self._cams:
                                img = self._grab_dxgi(name)
                                if img is not None:
                                    frames[name] = img
                        break
                    except Exception:
                        frames = {}
                        self._reset()  # display mode changed / access lost -> rebuild once
            out = None
            missing = [m for m in mons if m[0] not in frames]
            if missing or not frames:
                x, y, w, h, data = winapi.grab_virtual_screen()
                out = QImage(data, w, h, w * 4, QImage.Format_RGB32).copy()
            else:
                out = QImage(vw, vh, QImage.Format_RGB32)
                out.fill(0)
            if frames:
                p = QPainter(out)
                for name, (l, t, r, b) in mons:
                    img = frames.get(name)
                    if img is not None:
                        target = QRect(l - vx, t - vy, r - l, b - t)
                        if img.size() == target.size():
                            p.drawImage(target.topLeft(), img)
                        else:
                            p.drawImage(target, img)
                p.end()
            return out, vx, vy


grabber = Grabber()
