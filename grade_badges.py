"""Circular move grade badges for the Tk interface."""

from __future__ import annotations

import math
import tkinter as tk

from analysis_core import LABELS


SYMBOLS = {
    "brilliant": "!!", "great": "!", "best": "★",
    "excellent": "thumb", "good": "check", "book": "book",
    "forced": "arrow", "inaccuracy": "?!", "mistake": "?",
    "miss": "cross", "blunder": "??",
}


def text_color(code: str) -> str:
    """Keep category text readable against the application's dark background."""
    color = LABELS[code][1]
    channels = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(value * .65 + 255 * .35):02x}" for value in channels)


def draw_badge(canvas: tk.Canvas, code: str | None, size: int, *,
               origin: tuple[float, float] = (0, 0), clear: bool = True,
               tag: str = "grade_badge") -> None:
    """Draw a grade disc in a widget or over a piece on the board."""
    canvas.delete("all" if clear else tag)
    if code not in LABELS:
        return
    def at(*values: float) -> list[float]:
        return [value + origin[index % 2] for index, value in enumerate(values)]

    def oval(*values: float, **options: object) -> None:
        canvas.create_oval(*at(*values), tags=tag, **options)

    def line(*values: float, **options: object) -> None:
        canvas.create_line(*at(*values), tags=tag, **options)

    def polygon(*values: float, **options: object) -> None:
        canvas.create_polygon(*at(*values), tags=tag, **options)

    def label(x: float, y: float, **options: object) -> None:
        canvas.create_text(*at(x, y), tags=tag, **options)

    color = LABELS[code][1]
    center = size / 2
    pad = max(2, size * .06)
    oval(pad, pad, size - pad, size - pad,
         fill=color, outline="#e8e6dd", width=max(1, size * .025))
    symbol = SYMBOLS[code]
    white = "#ffffff"
    scale = size / 48
    if symbol == "check":
        line(13*scale, 25*scale, 21*scale, 32*scale, 35*scale, 17*scale,
             fill=white, width=max(2, 5*scale), capstyle="round", joinstyle="round")
    elif symbol == "arrow":
        line(13*scale, 24*scale, 34*scale, 24*scale,
             fill=white, width=max(2, 5*scale), capstyle="round", arrow="last",
             arrowshape=(9*scale, 11*scale, 5*scale))
    elif symbol == "cross":
        for x1, y1, x2, y2 in ((16, 16, 32, 32), (32, 16, 16, 32)):
            line(x1*scale, y1*scale, x2*scale, y2*scale,
                 fill=white, width=max(2, 6*scale), capstyle="round")
    elif symbol == "book":
        polygon(*[v*scale for v in (9, 15, 16, 13, 23, 16, 23, 34, 16, 31, 9, 32)],
                fill=white, outline="")
        polygon(*[v*scale for v in (25, 16, 32, 13, 39, 15, 39, 32, 32, 31, 25, 34)],
                fill=white, outline="")
        line(24*scale, 16*scale, 24*scale, 34*scale,
             fill="#e9dccc", width=max(1, scale))
    elif symbol == "thumb":
        polygon(*[v*scale for v in (
            10, 22, 16, 22, 16, 34, 10, 34,
            10, 22)], fill=white, outline="")
        polygon(*[v*scale for v in (
            18, 21, 23, 15, 25, 10, 28, 11, 29, 15,
            27, 21, 36, 21, 38, 24, 34, 35, 18, 35
        )], fill=white, outline="")
    elif symbol == "★":
        points = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            radius = 17*scale if index % 2 == 0 else 8*scale
            points.extend((center + radius*math.cos(angle), center + radius*math.sin(angle)))
        polygon(*points, fill=white, outline="")
    else:
        font_size = int(size * (.51 if len(symbol) == 1 else .43))
        label(center, center - scale, text=symbol,
              fill=white, font=("Segoe UI", font_size, "bold"))

    if size >= 40 and code in ("brilliant", "best"):
        # The small emblem above these two grades follows the chart reference.
        x, y, radius = center, 4*scale, 6*scale
        oval(x-radius, y-radius, x+radius, y+radius,
             fill=color, outline=white, width=max(1, scale))
        emblem = "♛" if code == "brilliant" else "★"
        label(x, y, text=emblem, fill=white,
              font=("Segoe UI Symbol", max(6, int(8*scale)), "bold"))


def make_badge(parent: tk.Misc, code: str | None, size: int = 30) -> tk.Canvas:
    badge = tk.Canvas(parent, width=size, height=size, bg="#292b25",
                      highlightthickness=0, borderwidth=0)
    draw_badge(badge, code, size)
    return badge
