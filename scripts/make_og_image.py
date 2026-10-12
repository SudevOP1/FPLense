"""Write ``web/public/og.png``: the 1200x630 Open Graph image shown when a FPLense link is shared.

Drawn with Pillow (no external assets, no player photos). Re-run only when the branding changes:

    python scripts/make_og_image.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "og.png"
NAVY, CORAL, WHITE, MUTED = (14, 24, 52), (255, 107, 87), (255, 255, 255), (163, 173, 204)
GRASS = [(34, 120, 72), (28, 104, 62)]


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(img)
    # a mown-pitch panel on the right with an XI of dots in a 3-4-3
    px, py, pw, ph = 720, 60, 420, 510
    for k in range(10):
        d.rectangle([px, py + k * ph // 10, px + pw, py + (k + 1) * ph // 10], fill=GRASS[k % 2])
    d.rectangle([px + 14, py + 14, px + pw - 14, py + ph - 14], outline=(255, 255, 255), width=3)
    rows = [[0.5], [0.25, 0.5, 0.75], [0.15, 0.38, 0.62, 0.85], [0.25, 0.5, 0.75]]
    for r, xs in enumerate(rows):
        y = py + ph - 70 - r * 120
        for x in xs:
            cx = px + int(x * pw)
            colour = CORAL if (r, x) == (3, 0.5) else WHITE
            d.ellipse([cx - 22, y - 22, cx + 22, y + 22], fill=colour)
    # wordmark and pitch
    big = font(120, bold=True)
    d.text((70, 150), "FPL", font=big, fill=WHITE)
    d.text((70 + d.textlength("FPL", font=big), 150), "ense", font=big, fill=CORAL)
    d.text((72, 300), "Expected points for every player", font=font(38), fill=WHITE)
    d.text((72, 350), "and the best legal £100m squad.", font=font(38), fill=WHITE)
    d.text((72, 460), "LightGBM forecasts · integer-program optimizer", font=font(28), fill=MUTED)
    d.text(
        (72, 500), "Compare teams · plan transfers · replay the season", font=font(28), fill=MUTED
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
