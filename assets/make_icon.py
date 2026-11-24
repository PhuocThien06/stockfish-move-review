"""Generate the Stockfish Review desktop and window icons."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


HERE = Path(__file__).resolve().parent
SIZE = 512


def make_icon() -> Image.Image:
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((38, 47, 474, 483), radius=105,
                                  fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((30, 26, 482, 478), radius=106,
                                            fill=255)
    gradient = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    upper, lower = (151, 207, 92), (58, 117, 46)
    for y in range(26, 479):
        fraction = (y - 26) / 452
        color = tuple(round(a * (1 - fraction) + b * fraction)
                      for a, b in zip(upper, lower)) + (255,)
        grad_draw.line((30, y, 482, y), fill=color)
    gradient.putalpha(mask)
    shadow.alpha_composite(gradient)
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle((36, 32, 476, 472), radius=101,
                           outline=(220, 246, 181, 180), width=7)
    font_path = Path("C:/Windows/Fonts/seguisym.ttf")
    if not font_path.is_file():
        font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 354)
    symbol = "♞"
    bounds = draw.textbbox((0, 0), symbol, font=font, stroke_width=6)
    x = (SIZE - (bounds[2] - bounds[0])) / 2 - bounds[0]
    y = (SIZE - (bounds[3] - bounds[1])) / 2 - bounds[1] - 8
    draw.text((x, y), symbol, font=font, fill="#f9f6e9",
              stroke_width=6, stroke_fill="#264626")
    return shadow


if __name__ == "__main__":
    image = make_icon()
    image.save(HERE / "stockfish_review.png")
    image.save(HERE / "stockfish_review.ico", format="ICO",
               sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
