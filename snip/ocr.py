"""Text recognition with the OCR engine built into Windows (fully offline)."""
import asyncio
import re

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt


class OcrUnavailable(Exception):
    pass


def _png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


async def _recognize(data):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable("No OCR language is installed in Windows.")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bmp)
    lines = []
    for ln in result.lines:
        words = []
        for wd in ln.words:
            r = wd.bounding_rect
            words.append((wd.text, (r.x, r.y, r.width, r.height)))
        if words:
            lines.append(words)
    return lines


def recognize(img):
    """Returns lines: [[(word, QRectF in image px), ...], ...]."""
    try:
        from winrt.windows.media.ocr import OcrEngine
        max_dim = OcrEngine.max_image_dimension or 10000
    except Exception as e:
        raise OcrUnavailable(f"Windows OCR is not available: {e}")
    scale = 1.0
    longest = max(img.width(), img.height())
    if longest < 1600:
        scale = min(3.0, 2000 / max(1, longest))  # small text reads much better upscaled
    if longest * scale > max_dim:
        scale = max_dim / longest
    work = img
    if abs(scale - 1.0) > 0.01:
        work = img.scaled(int(img.width() * scale), int(img.height() * scale),
                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
    raw = asyncio.run(_recognize(_png_bytes(work)))
    out = []
    for words in raw:
        out.append([(t, QRectF(x / scale, y / scale, w / scale, h / scale)) for t, (x, y, w, h) in words])
    return out


_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def lines_to_text(lines):
    rows = []
    for words in lines:
        sep = "" if any(_CJK.search(w) for w, _ in words) else " "
        rows.append(sep.join(w for w, _ in words))
    return "\n".join(rows)
