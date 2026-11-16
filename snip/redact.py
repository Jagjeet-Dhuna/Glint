"""Find sensitive text (emails, phone numbers, cards, IPs, keys...) in OCR output."""
import re

from PySide6.QtCore import QRectF

PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("card", re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{2,4}[\s.\-]?\d{3,4}[\s.\-]?\d{3,5}")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    # API keys / tokens: long runs mixing letters and digits (sk-..., ghp_..., AKIA...)
    ("key", re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")),
]


def _luhn(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def _valid(kind, text):
    digits = re.sub(r"\D", "", text)
    if kind == "card":
        return 13 <= len(digits) <= 19 and _luhn(digits)
    if kind == "phone":
        return 9 <= len(digits) <= 15
    if kind == "ip":
        return all(0 <= int(x) <= 255 for x in text.split("."))
    if kind == "key":
        return bool(re.search(r"\d", text)) and bool(re.search(r"[A-Za-z]", text))
    return True


_TOKEN_PART = re.compile(r"^[A-Za-z0-9_\-]+$")


def _grow_token(words, spans, idxs):
    """OCR often splits long tokens into pieces ("ghp_A1" "b2C3..."). Pull in touching fragments."""
    idxs = sorted(idxs)

    def close(i, j):
        a, b = spans[i][2], spans[j][2]
        gap = b.left() - a.right() if j > i else a.left() - b.right()
        return gap < max(a.height(), b.height()) * 0.6

    i = idxs[0]
    while i - 1 >= 0 and _TOKEN_PART.match(words[i - 1][0]) and close(i, i - 1) and re.search(r"[\d_]", words[i - 1][0]):
        i -= 1
        idxs.insert(0, i)
    j = idxs[-1]
    while j + 1 < len(words) and _TOKEN_PART.match(words[j + 1][0]) and close(j, j + 1) and re.search(r"[\d_]", words[j + 1][0]):
        j += 1
        idxs.append(j)
    return idxs


def find_sensitive(lines):
    """lines from ocr.recognize -> list of (kind, QRectF) to cover."""
    hits = []
    for words in lines:
        text, spans = "", []
        for w, rect in words:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(w), rect))
            text += w
        taken = []
        for kind, rx in PATTERNS:
            for m in rx.finditer(text):
                a, b = m.span()
                if any(a < tb and b > ta for ta, tb in taken):
                    continue
                if not _valid(kind, m.group()):
                    continue
                idxs = [i for i, (sa, sb, _) in enumerate(spans) if sa < b and sb > a]
                if not idxs:
                    continue
                if kind == "key":
                    idxs = _grow_token(words, spans, idxs)
                rects = [spans[i][2] for i in idxs]
                u = QRectF(rects[0])
                for r in rects[1:]:
                    u = u.united(r)
                pad = max(2.0, u.height() * 0.18)
                hits.append((kind, u.adjusted(-pad, -pad, pad, pad)))
                taken.append((a, b))
    return hits


def make_shapes(hits, width=4):
    """Pixelate shapes for each hit. Tagged "redact" so they can be unhidden later."""
    return [{"kind": "blur", "pts": [[r.left(), r.top()], [r.right(), r.bottom()]], "color": "#000000",
             "width": max(4, width), "fill": False, "shadow": False, "text": "", "font": 24, "number": 0,
             "redact": True, "label": kind} for kind, r in hits]


def auto_hide(img):
    """OCR the image and return redact shapes for anything sensitive."""
    from . import ocr
    return make_shapes(find_sensitive(ocr.recognize(img)))


def strip(shapes):
    return [s for s in shapes if not s.get("redact")]


def count(shapes):
    return sum(1 for s in shapes if s.get("redact"))
