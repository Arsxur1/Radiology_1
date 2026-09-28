"""Тепловая карта «куда смотрела модель» для находки-черновика (SR-1, раздел 11).

Карта — подсказка для врача, а не разметка патологии и не измерение: по ней нельзя
считать размеры, она не попадает в заключение и в обучающие метки. Хранится как
полупрозрачный PNG (RGBA) того же кадра, что и превью снимка, и накладывается поверх.

Кодирование PNG — на чистом Python (zlib), без numpy/Pillow: работает и на
продуктивном сервере без тяжёлых зависимостей.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib

Grid = list[list[float]]

# Значения ниже порога не окрашиваются — фон снимка остаётся читаемым.
MIN_VISIBLE = 0.35
MAX_ALPHA = 150


def normalize(grid: Grid) -> Grid:
    lo = min(min(r) for r in grid)
    hi = max(max(r) for r in grid)
    span = hi - lo
    if span <= 0:
        return [[0.0 for _ in r] for r in grid]
    return [[(v - lo) / span for v in r] for r in grid]


def _colormap(v: float) -> tuple[int, int, int]:
    """Сине-жёлто-красная шкала (без зелёного — читаемо на сером снимке)."""
    if v < 0.5:
        t = v / 0.5
        return int(255 * t), int(200 * t), int(255 * (1 - t))
    t = (v - 0.5) / 0.5
    return 255, int(200 * (1 - t)), 0


def _png(width: int, height: int, rgba_rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rgba_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def to_png(grid: Grid) -> bytes:
    """Карта значимости (любой масштаб) → полупрозрачный PNG той же сетки.

    Браузер растягивает PNG до размера превью (CSS), сглаживание — на стороне клиента.
    """
    norm = normalize(grid)
    rows = []
    for r in norm:
        row = bytearray()
        for v in r:
            if v < MIN_VISIBLE:
                row += b"\x00\x00\x00\x00"
            else:
                red, green, blue = _colormap(v)
                alpha = int(MAX_ALPHA * (v - MIN_VISIBLE) / (1 - MIN_VISIBLE))
                row += bytes((red, green, blue, alpha))
        rows.append(bytes(row))
    return _png(len(norm[0]), len(norm), rows)


def stub_grid(seed_text: str, size: int = 32) -> Grid:
    """Детерминированное «пятно» для заглушки модели (контур и демо без GPU)."""
    h = hashlib.sha256(seed_text.encode()).digest()
    cx, cy = 0.25 + 0.5 * h[0] / 255, 0.25 + 0.5 * h[1] / 255
    sigma = 0.08 + 0.08 * h[2] / 255
    return [
        [math.exp(-(((x + 0.5) / size - cx) ** 2 + ((y + 0.5) / size - cy) ** 2) / (2 * sigma**2))
         for x in range(size)]
        for y in range(size)
    ]
