"""Precise scrolling via Windows UI Automation (the accessibility API).

Many apps (browsers, File Explorer, Office, most standard controls) report their exact scroll position
and let other programs set it. When that's available, Glint knows exactly how far the page moved
instead of guessing from pixels, and Auto mode can scroll without simulated mouse input.
Never used for games.
"""
_uia = None
_U = None


def _init():
    global _uia, _U
    if _uia is not None:
        return _uia
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # already initialised on this thread (Qt does that)
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as U
    _U = U
    _uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    return _uia


SCROLL_PATTERN = 10004
NO_SCROLL = -1.0


class ScrollSource:
    """The scrollable element under a point, if the app exposes one."""

    def __init__(self, pattern):
        self.sp = pattern

    @classmethod
    def at(cls, x, y):
        try:
            from ctypes import wintypes as W
            uia = _init()
            el = uia.ElementFromPoint(W.POINT(int(x), int(y)))
            walker = uia.ControlViewWalker
            for _ in range(30):
                if not el:
                    return None
                try:
                    unk = el.GetCurrentPattern(SCROLL_PATTERN)
                except Exception:
                    unk = None
                if unk:
                    sp = unk.QueryInterface(_U.IUIAutomationScrollPattern)
                    if sp.CurrentVerticallyScrollable:
                        return cls(sp)
                el = walker.GetParentElement(el)
        except Exception:
            return None
        return None

    def percent(self):
        """Vertical position 0..100, or None if it can't be read right now."""
        try:
            p = float(self.sp.CurrentVerticalScrollPercent)
            return p if p >= 0 else None
        except Exception:
            return None

    def view_size(self):
        """How much of the content is visible, in percent (e.g. 23 = about a quarter)."""
        try:
            v = float(self.sp.CurrentVerticalViewSize)
            return v if 0 < v <= 100 else None
        except Exception:
            return None

    def set_percent(self, p):
        try:
            self.sp.SetScrollPercent(NO_SCROLL, max(0.0, min(100.0, float(p))))
            return True
        except Exception:
            return False
